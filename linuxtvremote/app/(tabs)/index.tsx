import { useEffect, useRef, useState } from 'react';
import * as SecureStore from 'expo-secure-store';
import {
  Alert,
  AppState,
  AppStateStatus,
  Modal,
  PanResponder,
  Pressable,
  ScrollView,
  StyleProp,
  StyleSheet,
  Text,
  TextInput,
  TextStyle,
  View,
  ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

type ConnectionState = 'Disconnected' | 'Connecting...' | 'Connected' | 'Error';
type ControlTab = 'remote' | 'keyboard' | 'touchpad';
type AuthState =
  | 'Saved credentials loaded'
  | 'No saved credentials'
  | 'Authenticating...'
  | 'Authenticated'
  | 'Authentication required'
  | 'Authentication failed';

const HOST_KEY = 'linuxtv_remote_host';
const PORT_KEY = 'linuxtv_remote_port';
const USERNAME_KEY = 'linuxtv_remote_username';
const PASSWORD_KEY = 'linuxtv_remote_password';
const DEFAULT_PORT = '8765';
const RECONNECT_DELAY_MS = 3000;
const REMOTE_REPEAT_DELAY_MS = 320;
const REMOTE_REPEAT_INTERVAL_MS = 90;

export default function RemoteScreen() {
  const [ipAddress, setIpAddress] = useState('');
  const [port, setPort] = useState(DEFAULT_PORT);
  const [status, setStatus] = useState<ConnectionState>('Disconnected');
  const [authStatus, setAuthStatus] = useState<AuthState>('No saved credentials');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [lastAction, setLastAction] = useState('None');
  const [lastMessage, setLastMessage] = useState('Looking for saved LinuxTV remote info');
  const [hasSavedSetup, setHasSavedSetup] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);
  const [isMenuVisible, setIsMenuVisible] = useState(false);
  const [activeTab, setActiveTab] = useState<ControlTab>('remote');
  const [keyboardDraft, setKeyboardDraft] = useState('');
  const socketRef = useRef<WebSocket | null>(null);
  const pendingOutboundRef = useRef<{
    label: string;
    message: string;
    trackLastAction: boolean;
    updateLastMessage: boolean;
  } | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const repeatTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const repeatIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const shouldReconnectRef = useRef(false);
  const touchpadGestureRef = useRef({ lastDx: 0, lastDy: 0 });
  const connectWithConfigRef = useRef<
    ((config?: {
      ipAddress?: string;
      password?: string;
      port?: string;
      username?: string;
    }) => Promise<void>) | null
  >(null);
  const latestConfigRef = useRef({
    ipAddress: '',
    port: DEFAULT_PORT,
    username: '',
    password: '',
  });

  useEffect(() => {
    latestConfigRef.current = { ipAddress, port, username, password };
  }, [ipAddress, port, username, password]);

  const clearReconnectTimer = () => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  };

  const clearRepeatTimers = () => {
    if (repeatTimeoutRef.current) {
      clearTimeout(repeatTimeoutRef.current);
      repeatTimeoutRef.current = null;
    }
    if (repeatIntervalRef.current) {
      clearInterval(repeatIntervalRef.current);
      repeatIntervalRef.current = null;
    }
  };

  const disconnectSocket = () => {
    if (socketRef.current) {
      socketRef.current.onopen = null;
      socketRef.current.onclose = null;
      socketRef.current.onerror = null;
      socketRef.current.onmessage = null;
      socketRef.current.close();
      socketRef.current = null;
    }
  };

  const scheduleReconnect = () => {
    clearReconnectTimer();
    if (!shouldReconnectRef.current) {
      return;
    }

    reconnectTimeoutRef.current = setTimeout(() => {
      const config = latestConfigRef.current;
      if (!config.ipAddress.trim()) {
        return;
      }
      void connectWithConfig(config);
    }, RECONNECT_DELAY_MS);
  };

  const authenticate = async (
    credentials?: { username: string; password: string },
    persist = false
  ) => {
    const activeSocket = socketRef.current;
    const selectedUsername = (credentials?.username ?? latestConfigRef.current.username).trim();
    const selectedPassword = credentials?.password ?? latestConfigRef.current.password;

    if (!selectedUsername || !selectedPassword) {
      Alert.alert('Missing credentials', 'Enter the username and password from LinuxTV settings.');
      return false;
    }

    if (persist) {
      await Promise.all([
        SecureStore.setItemAsync(USERNAME_KEY, selectedUsername),
        SecureStore.setItemAsync(PASSWORD_KEY, selectedPassword),
      ]);
      setUsername(selectedUsername);
      setPassword(selectedPassword);
    }

    if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) {
      setAuthStatus('Saved credentials loaded');
      setLastMessage('Credentials saved on this phone. Waiting for LinuxTV to come online.');
      return true;
    }

    setAuthStatus('Authenticating...');
    activeSocket.send(
      JSON.stringify({
        type: 'auth',
        username: selectedUsername,
        password: selectedPassword,
      })
    );
    return true;
  };

  const connectWithConfig = async (config?: {
    ipAddress?: string;
    port?: string;
    username?: string;
    password?: string;
  }) => {
    const cleanedIpAddress = (config?.ipAddress ?? latestConfigRef.current.ipAddress).trim();
    const cleanedPort = (config?.port ?? latestConfigRef.current.port).trim() || DEFAULT_PORT;
    const selectedUsername = config?.username ?? latestConfigRef.current.username;
    const selectedPassword = config?.password ?? latestConfigRef.current.password;

    if (!cleanedIpAddress) {
      setStatus('Disconnected');
      setLastMessage('Enter the LinuxTV IP address to finish setup.');
      return;
    }

    clearReconnectTimer();
    shouldReconnectRef.current = true;
    pendingOutboundRef.current = null;

    if (socketRef.current) {
      disconnectSocket();
    }

    const target = `${cleanedIpAddress}:${cleanedPort}`;
    setStatus('Connecting...');
    setLastMessage(`Trying ${target}`);

    try {
      const ws = new WebSocket(`ws://${target}`);
      socketRef.current = ws;

      ws.onopen = () => {
        setStatus('Connected');
        setLastMessage('Remote session is live');
        if (selectedUsername.trim() && selectedPassword) {
          void authenticate({
            username: selectedUsername,
            password: selectedPassword,
          });
        }
      };

      ws.onclose = () => {
        socketRef.current = null;
        setStatus('Disconnected');
        setLastMessage(`Waiting for LinuxTV at ${target}`);
        scheduleReconnect();
      };

      ws.onerror = () => {
        setStatus('Error');
        setLastMessage(`Unable to reach LinuxTV at ${target}`);
      };

      ws.onmessage = (event) => {
        const rawMessage = String(event.data);
        try {
          const payload = JSON.parse(rawMessage) as {
            action?: string;
            error?: string;
            event?: string;
            key?: string;
            status?: string;
            type?: string;
          };
          if (payload.status === 'auth_ok') {
            setAuthStatus('Authenticated');
            setLastMessage('Authentication successful');
            if (pendingOutboundRef.current && socketRef.current?.readyState === WebSocket.OPEN) {
              const pendingOutbound = pendingOutboundRef.current;
              pendingOutboundRef.current = null;
              socketRef.current.send(pendingOutbound.message);
              if (pendingOutbound.trackLastAction) {
                setLastAction(pendingOutbound.label);
              }
              if (pendingOutbound.updateLastMessage) {
                setLastMessage(`Sent ${pendingOutbound.label}`);
              }
            }
            return;
          }
          if (payload.status === 'auth_error') {
            setAuthStatus('Authentication failed');
            setLastMessage(payload.error ?? 'Invalid credentials');
            pendingOutboundRef.current = null;
            return;
          }
          if (payload.status === 'auth_required') {
            setAuthStatus('Authentication required');
            setLastMessage('Sign in with the desktop username and password');
            if (selectedUsername.trim() && selectedPassword) {
              void authenticate({
                username: selectedUsername,
                password: selectedPassword,
              });
            }
            return;
          }
          if (payload.status === 'ok') {
            setAuthStatus((current) =>
              current === 'Authenticated' ? current : 'Authenticated'
            );
            if (payload.type === 'pointer') {
              if (payload.event === 'tap') {
                setLastAction('Touchpad tap');
                setLastMessage('Touchpad tap');
              } else if (payload.event === 'click') {
                setLastAction('Left click');
                setLastMessage('Left click');
              } else if (payload.event === 'right_click') {
                setLastAction('Right click');
                setLastMessage('Right click');
              }
            } else if (payload.type === 'text') {
              setLastMessage('Typed text in the active app');
            } else if (payload.type === 'key') {
              setLastAction(`Key ${payload.key ?? ''}`.trim());
              setLastMessage(`Sent ${payload.key ?? 'key'}`);
            } else {
              setLastMessage(`Sent ${payload.action ?? 'command'}`);
            }
            return;
          }
        } catch {
          setLastMessage(rawMessage);
        }
      };
    } catch {
      setStatus('Error');
      setLastMessage('Failed to create WebSocket');
      scheduleReconnect();
    }
  };

  connectWithConfigRef.current = connectWithConfig;

  const saveSetupAndConnect = async () => {
    const cleanedIpAddress = ipAddress.trim();
    const cleanedPort = port.trim() || DEFAULT_PORT;

    if (!cleanedIpAddress) {
      Alert.alert('Missing address', 'Enter the LinuxTV IP address first.');
      return;
    }

    if (username.trim() || password) {
      const didSaveCredentials = await authenticate(
        { username, password },
        Boolean(username.trim() && password)
      );

      if (!didSaveCredentials) {
        return;
      }
    }

    await Promise.all([
      SecureStore.setItemAsync(HOST_KEY, cleanedIpAddress),
      SecureStore.setItemAsync(PORT_KEY, cleanedPort),
    ]);

    setIpAddress(cleanedIpAddress);
    setPort(cleanedPort);
    setHasSavedSetup(true);
    setLastMessage(`Saved ${cleanedIpAddress}:${cleanedPort}. Waiting for LinuxTV.`);
    void connectWithConfig({
      ipAddress: cleanedIpAddress,
      port: cleanedPort,
      username,
      password,
    });
  };

  const clearSavedSetup = async () => {
    shouldReconnectRef.current = false;
    clearReconnectTimer();
    disconnectSocket();

    await Promise.all([
      SecureStore.deleteItemAsync(HOST_KEY),
      SecureStore.deleteItemAsync(PORT_KEY),
      SecureStore.deleteItemAsync(USERNAME_KEY),
      SecureStore.deleteItemAsync(PASSWORD_KEY),
    ]);

    pendingOutboundRef.current = null;
    setHasSavedSetup(false);
    setIpAddress('');
    setPort(DEFAULT_PORT);
    setUsername('');
    setPassword('');
    setStatus('Disconnected');
    setAuthStatus('No saved credentials');
    setLastAction('None');
    setLastMessage('Saved setup removed. Enter the LinuxTV info again.');
    setActiveTab('remote');
    setKeyboardDraft('');
  };

  const confirmLogout = () => {
    setIsMenuVisible(false);
    Alert.alert(
      'Logout?',
      'This removes the saved IP address, port, username, and password from this phone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Logout',
          style: 'destructive',
          onPress: () => {
            void clearSavedSetup();
          },
        },
      ]
    );
  };

  const sendPayload = (
    payload: Record<string, unknown>,
    label: string,
    options?: {
      queueWhenAuthNeeded?: boolean;
      trackLastAction?: boolean;
      updateLastMessage?: boolean;
    }
  ) => {
    const {
      queueWhenAuthNeeded = true,
      trackLastAction = true,
      updateLastMessage = true,
    } = options ?? {};

    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      setLastMessage('Waiting for LinuxTV to come online');
      scheduleReconnect();
      return;
    }

    const message = JSON.stringify(payload);

    if (
      authStatus !== 'Authenticated' &&
      latestConfigRef.current.username.trim() &&
      latestConfigRef.current.password
    ) {
      if (queueWhenAuthNeeded) {
        pendingOutboundRef.current = {
          label,
          message,
          trackLastAction,
          updateLastMessage,
        };
      }
      void authenticate({
        username: latestConfigRef.current.username,
        password: latestConfigRef.current.password,
      });
      return;
    }

    socketRef.current.send(message);
    if (trackLastAction) {
      setLastAction(label);
    }
    if (updateLastMessage) {
      setLastMessage(`Sending ${label}`);
    }
  };

  const sendAction = (action: string) => {
    sendPayload({ action }, action);
  };

  const confirmPowerAction = (action: 'SHUTDOWN' | 'REBOOT') => {
    setIsMenuVisible(false);
    const actionLabel = action === 'SHUTDOWN' ? 'Shutdown' : 'Reboot';
    const message =
      action === 'SHUTDOWN'
        ? 'Shut down the LinuxTV system now?'
        : 'Reboot the LinuxTV system now?';

    Alert.alert(actionLabel, message, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: actionLabel,
        style: 'destructive',
        onPress: () => sendAction(action),
      },
    ]);
  };

  const createRepeatingActionHandlers = (action: string) => ({
    onPress: () => sendAction(action),
    onPressIn: () => {
      clearRepeatTimers();
      repeatTimeoutRef.current = setTimeout(() => {
        sendAction(action);
        repeatIntervalRef.current = setInterval(() => {
          sendAction(action);
        }, REMOTE_REPEAT_INTERVAL_MS);
      }, REMOTE_REPEAT_DELAY_MS);
    },
    onPressOut: clearRepeatTimers,
  });

  const sendKeyboardText = () => {
    const text = keyboardDraft.trim();
    if (!text) {
      return;
    }
    sendPayload({ type: 'text', text }, 'Typed text');
    setKeyboardDraft('');
  };

  const sendSpecialKey = (key: 'ENTER' | 'SPACE' | 'BACKSPACE' | 'ESCAPE' | 'TAB') => {
    sendPayload({ type: 'key', key }, `Key ${key}`);
  };

  const sendPointerEvent = (
    event: 'move' | 'tap' | 'click' | 'right_click',
    payload?: { dx?: number; dy?: number }
  ) => {
    sendPayload(
      { type: 'pointer', event, ...payload },
      event === 'tap' ? 'Touchpad tap' : event === 'click' ? 'Left click' : 'Right click',
      {
        queueWhenAuthNeeded: event !== 'move',
        trackLastAction: event !== 'move',
        updateLastMessage: event !== 'move',
      }
    );
  };

  useEffect(() => {
    let active = true;

    const loadSavedSetup = async () => {
      const [storedHost, storedPort, storedUsername, storedPassword] = await Promise.all([
        SecureStore.getItemAsync(HOST_KEY),
        SecureStore.getItemAsync(PORT_KEY),
        SecureStore.getItemAsync(USERNAME_KEY),
        SecureStore.getItemAsync(PASSWORD_KEY),
      ]);

      if (!active) {
        return;
      }

      const nextHost = storedHost?.trim() ?? '';
      const nextPort = storedPort?.trim() || DEFAULT_PORT;
      const nextUsername = storedUsername ?? '';
      const nextPassword = storedPassword ?? '';

      setIpAddress(nextHost);
      setPort(nextPort);
      setUsername(nextUsername);
      setPassword(nextPassword);
      setHasSavedSetup(Boolean(nextHost));
      setAuthStatus(
        nextUsername && nextPassword ? 'Saved credentials loaded' : 'No saved credentials'
      );
      setLastMessage(
        nextHost
          ? `Saved ${nextHost}:${nextPort}. Waiting for LinuxTV.`
          : 'Enter the LinuxTV info once to keep this remote paired.'
      );
      setIsHydrated(true);

      if (nextHost) {
        shouldReconnectRef.current = true;
        void connectWithConfigRef.current?.({
          ipAddress: nextHost,
          port: nextPort,
          username: nextUsername,
          password: nextPassword,
        });
      }
    };

    void loadSavedSetup();

    return () => {
      active = false;
      shouldReconnectRef.current = false;
      clearRepeatTimers();
      clearReconnectTimer();
      disconnectSocket();
    };
  }, []);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState: AppStateStatus) => {
      if (nextState !== 'active' || !hasSavedSetup || !isHydrated) {
        return;
      }

      const activeSocket = socketRef.current;
      if (!activeSocket || activeSocket.readyState === WebSocket.CLOSED) {
        void connectWithConfigRef.current?.();
      }
    });

    return () => {
      subscription.remove();
    };
  }, [hasSavedSetup, isHydrated]);

  const showLoginScreen = !hasSavedSetup;
  const tabItems: { key: ControlTab; label: string }[] = [
    { key: 'remote', label: 'Remote' },
    { key: 'keyboard', label: 'Keyboard' },
    { key: 'touchpad', label: 'Touchpad' },
  ];
  const touchpadResponder = PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: () => {
      touchpadGestureRef.current = { lastDx: 0, lastDy: 0 };
    },
    onPanResponderMove: (_event, gestureState) => {
      const deltaX = Math.round((gestureState.dx - touchpadGestureRef.current.lastDx) * 1.2);
      const deltaY = Math.round((gestureState.dy - touchpadGestureRef.current.lastDy) * 1.2);

      if (Math.abs(deltaX) < 2 && Math.abs(deltaY) < 2) {
        return;
      }

      touchpadGestureRef.current = { lastDx: gestureState.dx, lastDy: gestureState.dy };
      sendPointerEvent('move', { dx: deltaX, dy: deltaY });
    },
    onPanResponderRelease: (_event, gestureState) => {
      if (Math.abs(gestureState.dx) < 8 && Math.abs(gestureState.dy) < 8) {
        sendPointerEvent('tap');
      }
    },
  });

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <Text style={styles.title}>LinuxTV</Text>
            <View
              style={[
                styles.statusDot,
                status === 'Connected' ? styles.statusOnline : styles.statusOffline,
              ]}
            />
          </View>
          {hasSavedSetup ? (
            <Pressable
              style={({ pressed }) => [
                styles.menuButton,
                pressed && styles.pressed,
                isMenuVisible && styles.menuButtonActive,
              ]}
              onPress={() => setIsMenuVisible((current) => !current)}>
              <Text style={styles.menuButtonText}>⚙</Text>
            </Pressable>
          ) : null}
        </View>

        {showLoginScreen ? (
          /* Login Screen */
          <View style={styles.loginContainer}>
            <Text style={styles.helperText}>Enter LinuxTV connection details</Text>
            <View style={styles.addressRow}>
              <TextInput
                value={ipAddress}
                onChangeText={setIpAddress}
                placeholder="IP address"
                placeholderTextColor="#8b949e"
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="numbers-and-punctuation"
                style={[styles.input, styles.ipInput]}
              />
              <TextInput
                value={port}
                onChangeText={setPort}
                placeholder="Port"
                placeholderTextColor="#8b949e"
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="number-pad"
                style={[styles.input, styles.portInput]}
              />
            </View>
            <TextInput
              value={username}
              onChangeText={setUsername}
              placeholder="Username"
              placeholderTextColor="#8b949e"
              autoCapitalize="none"
              autoCorrect={false}
              style={styles.input}
            />
            <TextInput
              value={password}
              onChangeText={setPassword}
              placeholder="Password"
              placeholderTextColor="#8b949e"
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              style={styles.input}
            />
            <Pressable
              style={[styles.actionButton, styles.primaryButton]}
              onPress={saveSetupAndConnect}>
              <Text style={styles.primaryButtonText}>Connect</Text>
            </Pressable>
          </View>
        ) : (
          /* Remote Control Interface */
          <View style={styles.remoteContainer}>
            {/* Status message */}
            <Text style={styles.statusMessage}>{lastMessage}</Text>

            {/* Tab Content */}
            {activeTab === 'remote' && (
              <View style={styles.remoteControl}>
                {/* D-Pad */}
                <View style={styles.dpadContainer}>
                  <ControlButton
                    label="▲"
                    {...createRepeatingActionHandlers('UP')}
                    style={styles.dpadButton}
                    textStyle={styles.dpadButtonText}
                  />
                  <View style={styles.dpadMiddle}>
                    <ControlButton
                      label="◀"
                      {...createRepeatingActionHandlers('LEFT')}
                      style={styles.dpadButton}
                      textStyle={styles.dpadButtonText}
                    />
                    <ControlButton
                      label="OK"
                      onPress={() => sendAction('SELECT')}
                      style={styles.okButton}
                      textStyle={styles.okButtonText}
                    />
                    <ControlButton
                      label="▶"
                      {...createRepeatingActionHandlers('RIGHT')}
                      style={styles.dpadButton}
                      textStyle={styles.dpadButtonText}
                    />
                  </View>
                  <ControlButton
                    label="▼"
                    {...createRepeatingActionHandlers('DOWN')}
                    style={styles.dpadButton}
                    textStyle={styles.dpadButtonText}
                  />
                </View>

                {/* Action Buttons */}
                <View style={styles.actionButtonsRow}>
                  <ControlButton
                    label="Back"
                    onPress={() => sendAction('BACK')}
                    style={styles.actionButtonSmall}
                    textStyle={styles.actionButtonText}
                  />
                  <ControlButton
                    label="Home"
                    onPress={() => sendAction('HOME')}
                    style={styles.actionButtonSmall}
                    textStyle={styles.actionButtonText}
                  />
                  <ControlButton
                    label="Menu"
                    onPress={() => sendAction('MENU')}
                    style={styles.actionButtonSmall}
                    textStyle={styles.actionButtonText}
                  />
                </View>

                <View style={styles.actionButtonsRow}>
                  <ControlButton
                    label="Close"
                    onPress={() => sendAction('CLOSE_APP')}
                    style={[styles.actionButtonSmall, styles.closeButtonSmall]}
                    textStyle={styles.closeButtonTextSmall}
                  />
                  <ControlButton
                    label="Play/Pause"
                    onPress={() => sendAction('PLAY_PAUSE')}
                    style={styles.actionButtonSmall}
                    textStyle={styles.actionButtonText}
                  />
                  <ControlButton
                    label="Info"
                    onPress={() => sendAction('INFO')}
                    style={styles.actionButtonSmall}
                    textStyle={styles.actionButtonText}
                  />
                </View>
              </View>
            )}

            {activeTab === 'keyboard' && (
              <View style={styles.keyboardContainer}>
                <TextInput
                  value={keyboardDraft}
                  onChangeText={setKeyboardDraft}
                  placeholder="Type text..."
                  placeholderTextColor="#8b949e"
                  autoCapitalize="none"
                  autoCorrect={false}
                  multiline
                  style={styles.keyboardInput}
                />
                <Pressable
                  style={[styles.actionButton, styles.primaryButton]}
                  onPress={sendKeyboardText}>
                  <Text style={styles.primaryButtonText}>Send Text</Text>
                </Pressable>
                <View style={styles.specialKeysRow}>
                  <ControlButton
                    label="Enter"
                    onPress={() => sendSpecialKey('ENTER')}
                    style={styles.keyButton}
                    textStyle={styles.keyButtonText}
                  />
                  <ControlButton
                    label="Space"
                    onPress={() => sendSpecialKey('SPACE')}
                    style={styles.keyButton}
                    textStyle={styles.keyButtonText}
                  />
                  <ControlButton
                    label="Backspace"
                    onPress={() => sendSpecialKey('BACKSPACE')}
                    style={styles.keyButton}
                    textStyle={styles.keyButtonText}
                  />
                </View>
                <View style={styles.specialKeysRow}>
                  <ControlButton
                    label="Esc"
                    onPress={() => sendSpecialKey('ESCAPE')}
                    style={styles.keyButton}
                    textStyle={styles.keyButtonText}
                  />
                  <ControlButton
                    label="Tab"
                    onPress={() => sendSpecialKey('TAB')}
                    style={styles.keyButton}
                    textStyle={styles.keyButtonText}
                  />
                  <ControlButton
                    label="Shift+Tab"
                    onPress={() => sendAction('SHIFT_TAB')}
                    style={styles.keyButton}
                    textStyle={styles.keyButtonText}
                  />
                </View>
              </View>
            )}

            {activeTab === 'touchpad' && (
              <View style={styles.touchpadContainer}>
                <View style={styles.touchpadSurface} {...touchpadResponder.panHandlers}>
                  <Text style={styles.touchpadText}>Touchpad</Text>
                  <Text style={styles.touchpadHint}>Tap to click • Drag to move</Text>
                </View>
                <View style={styles.touchpadButtons}>
                  <ControlButton
                    label="Click"
                    onPress={() => sendPointerEvent('click')}
                    style={styles.touchpadButton}
                    textStyle={styles.touchpadButtonText}
                  />
                  <ControlButton
                    label="Right Click"
                    onPress={() => sendPointerEvent('right_click')}
                    style={styles.touchpadButton}
                    textStyle={styles.touchpadButtonText}
                  />
                </View>
              </View>
            )}
          </View>
        )}

        {/* Bottom Tab Bar */}
        {!showLoginScreen && (
          <View style={styles.tabBar}>
            {tabItems.map((tab) => (
              <Pressable
                key={tab.key}
                style={({ pressed }) => [
                  styles.tabItem,
                  activeTab === tab.key && styles.tabItemActive,
                  pressed && styles.pressed,
                ]}
                onPress={() => setActiveTab(tab.key)}>
                <Text
                  style={[
                    styles.tabItemText,
                    activeTab === tab.key && styles.tabItemTextActive,
                  ]}>
                  {tab.label}
                </Text>
              </Pressable>
            ))}
          </View>
        )}
      </View>

      <Modal
        transparent
        animationType="fade"
        visible={isMenuVisible}
        onRequestClose={() => setIsMenuVisible(false)}>
        <Pressable style={styles.menuOverlay} onPress={() => setIsMenuVisible(false)}>
          <View style={styles.menuSheet}>
            <Pressable
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
              onPress={() => confirmPowerAction('SHUTDOWN')}>
              <Text style={styles.menuItemText}>Shutdown</Text>
            </Pressable>
            <Pressable
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
              onPress={() => confirmPowerAction('REBOOT')}>
              <Text style={styles.menuItemText}>Reboot</Text>
            </Pressable>
            <Pressable
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
              onPress={confirmLogout}>
              <Text style={styles.menuItemText}>Logout</Text>
            </Pressable>
          </View>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

function ControlButton({
  label,
  onPress,
  onPressIn,
  onPressOut,
  style,
  textStyle,
}: {
  label: string;
  onPress: () => void;
  onPressIn?: () => void;
  onPressOut?: () => void;
  style?: StyleProp<ViewStyle>;
  textStyle?: StyleProp<TextStyle>;
}) {
  return (
    <Pressable
      style={({ pressed }) => [style, pressed && styles.pressed]}
      onPress={onPress}
      onPressIn={onPressIn}
      onPressOut={onPressOut}>
      <Text style={textStyle}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#0a0e17',
  },
  container: {
    flex: 1,
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 0,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  title: {
    color: '#f0f6fc',
    fontSize: 28,
    fontWeight: '800',
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  statusOnline: {
    backgroundColor: '#238636',
  },
  statusOffline: {
    backgroundColor: '#da3633',
  },
  menuButton: {
    width: 42,
    height: 42,
    borderRadius: 21,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#21262d',
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuButtonActive: {
    borderColor: '#58a6ff',
    backgroundColor: '#30363d',
  },
  menuButtonText: {
    color: '#c9d1d9',
    fontSize: 18,
  },
  loginContainer: {
    flex: 1,
    justifyContent: 'center',
    gap: 14,
  },
  remoteContainer: {
    flex: 1,
    justifyContent: 'space-between',
  },
  statusMessage: {
    color: '#8b949e',
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 8,
  },
  remoteControl: {
    flex: 1,
    justifyContent: 'center',
    gap: 18,
  },
  dpadContainer: {
    alignItems: 'center',
    gap: 14,
    marginBottom: 22,
  },
  dpadMiddle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 24,
  },
  dpadButton: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
  },
  dpadButtonText: {
    color: '#f0f6fc',
    fontSize: 28,
    fontWeight: '800',
  },
  okButton: {
    width: 90,
    height: 90,
    borderRadius: 45,
    backgroundColor: '#238636',
    alignItems: 'center',
    justifyContent: 'center',
  },
  okButtonText: {
    color: '#ffffff',
    fontSize: 24,
    fontWeight: '800',
  },
  actionButtonsRow: {
    flexDirection: 'row',
    gap: 10,
  },
  actionButtonSmall: {
    flex: 1,
    minHeight: 50,
    borderRadius: 12,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionButtonText: {
    color: '#c9d1d9',
    fontSize: 15,
    fontWeight: '600',
  },
  closeButtonSmall: {
    backgroundColor: '#da3633',
    borderColor: '#da3633',
  },
  closeButtonTextSmall: {
    color: '#ffffff',
    fontWeight: '700',
  },
  keyboardContainer: {
    flex: 1,
    gap: 12,
  },
  keyboardInput: {
    flex: 1,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#0d1117',
    color: '#c9d1d9',
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 15,
    textAlignVertical: 'top',
  },
  specialKeysRow: {
    flexDirection: 'row',
    gap: 8,
  },
  keyButton: {
    flex: 1,
    minHeight: 48,
    borderRadius: 10,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
  },
  keyButtonText: {
    color: '#c9d1d9',
    fontSize: 14,
    fontWeight: '600',
  },
  touchpadContainer: {
    flex: 1,
    gap: 12,
  },
  touchpadSurface: {
    flex: 1,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#0d1117',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  touchpadText: {
    color: '#f0f6fc',
    fontSize: 22,
    fontWeight: '700',
  },
  touchpadHint: {
    color: '#8b949e',
    fontSize: 13,
  },
  touchpadButtons: {
    flexDirection: 'row',
    gap: 10,
  },
  touchpadButton: {
    flex: 1,
    minHeight: 50,
    borderRadius: 12,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
  },
  touchpadButtonText: {
    color: '#c9d1d9',
    fontSize: 15,
    fontWeight: '600',
  },
  tabBar: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: '#30363d',
    backgroundColor: '#161b22',
    marginTop: 12,
  },
  tabItem: {
    flex: 1,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabItemActive: {
    borderTopWidth: 2,
    borderTopColor: '#238636',
    backgroundColor: '#0d1117',
  },
  tabItemText: {
    color: '#8b949e',
    fontSize: 13,
    fontWeight: '600',
  },
  tabItemTextActive: {
    color: '#238636',
  },
  addressRow: {
    flexDirection: 'row',
    gap: 10,
  },
  ipInput: {
    flex: 1,
  },
  portInput: {
    width: 100,
  },
  input: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#0d1117',
    color: '#c9d1d9',
    paddingHorizontal: 16,
    paddingVertical: 13,
    fontSize: 15,
  },
  actionButton: {
    minHeight: 50,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
  },
  primaryButton: {
    backgroundColor: '#238636',
  },
  primaryButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '700',
  },
  helperText: {
    color: '#8b949e',
    fontSize: 14,
    lineHeight: 20,
    textAlign: 'center',
  },
  pressed: {
    opacity: 0.85,
    transform: [{ scale: 0.97 }],
  },
  menuOverlay: {
    flex: 1,
    backgroundColor: 'rgba(10, 14, 23, 0.6)',
    justifyContent: 'flex-start',
    paddingTop: 80,
    paddingHorizontal: 20,
    alignItems: 'flex-end',
  },
  menuSheet: {
    minWidth: 150,
    borderRadius: 12,
    backgroundColor: '#161b22',
    borderWidth: 1,
    borderColor: '#30363d',
    overflow: 'hidden',
  },
  menuItem: {
    paddingHorizontal: 18,
    paddingVertical: 14,
  },
  menuItemPressed: {
    backgroundColor: '#21262d',
  },
  menuItemText: {
    color: '#58a6ff',
    fontSize: 15,
    fontWeight: '600',
  },
});
