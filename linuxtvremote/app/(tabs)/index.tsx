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

import {
  DemoRepository,
  type AuthState,
  type ConnectionState,
  type DemoApp,
  RealServerRepository,
  type RemoteRepository,
  type RepositoryState,
} from '@/lib/remote-repository';

const HOST_KEY = 'linuxtv_remote_host';
const PORT_KEY = 'linuxtv_remote_port';
const USERNAME_KEY = 'linuxtv_remote_username';
const PASSWORD_KEY = 'linuxtv_remote_password';
const DEMO_MODE_KEY = 'linuxtv_remote_demo_mode';
const DEFAULT_PORT = '8765';
const REMOTE_REPEAT_DELAY_MS = 320;
const REMOTE_REPEAT_INTERVAL_MS = 90;

type ScreenRepositoryState = RepositoryState & {
  authStatus: AuthState;
  status: ConnectionState;
};

type TabType = 'remote' | 'keyboard' | 'touchpad';

const DEFAULT_REPOSITORY_STATE: ScreenRepositoryState = {
  authStatus: 'No saved credentials',
  deviceName: '',
  isDemoMode: false,
  lastAction: 'None',
  lastMessage: 'Looking for saved LinuxTV remote info',
  status: 'Disconnected',
};

export default function RemoteScreen() {
  const [ipAddress, setIpAddress] = useState('');
  const [port, setPort] = useState(DEFAULT_PORT);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [hasSavedSetup, setHasSavedSetup] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);
  const [isMenuVisible, setIsMenuVisible] = useState(false);
  const [activeTab, setActiveTab] = useState<TabType>('remote');
  const [keyboardDraft, setKeyboardDraft] = useState('');
  const [demoApps, setDemoApps] = useState<DemoApp[]>([]);
  const [repositoryState, setRepositoryState] = useState<ScreenRepositoryState>(
    DEFAULT_REPOSITORY_STATE
  );
  const repositoryRef = useRef<RemoteRepository | null>(null);
  const repeatTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const repeatIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const touchpadGestureRef = useRef({ lastDx: 0, lastDy: 0 });

  const applyRepositoryUpdate = (update: Partial<RepositoryState>) => {
    setRepositoryState((current) => ({ ...current, ...update }));
  };

  const createRepository = (isDemoMode: boolean) => {
    repositoryRef.current?.dispose();
    const nextRepository = isDemoMode
      ? new DemoRepository(applyRepositoryUpdate)
      : new RealServerRepository(applyRepositoryUpdate);
    repositoryRef.current = nextRepository;
    setDemoApps(nextRepository.getDemoApps());
    return nextRepository;
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

  const activateDemoMode = async (persist = true) => {
    const repository = createRepository(true);
    if (persist) {
      await SecureStore.setItemAsync(DEMO_MODE_KEY, 'true');
    }
    setHasSavedSetup(true);
    setActiveTab('remote');
    setKeyboardDraft('');
    await repository.connect();
  };

  const saveSetupAndConnect = async () => {
    const cleanedIpAddress = ipAddress.trim();
    const cleanedPort = port.trim() || DEFAULT_PORT;

    if (!cleanedIpAddress) {
      Alert.alert('Missing address', 'Enter the LinuxTV IP address first.');
      return;
    }

    await Promise.all([
      SecureStore.setItemAsync(HOST_KEY, cleanedIpAddress),
      SecureStore.setItemAsync(PORT_KEY, cleanedPort),
      SecureStore.setItemAsync(USERNAME_KEY, username.trim()),
      SecureStore.setItemAsync(PASSWORD_KEY, password),
      SecureStore.deleteItemAsync(DEMO_MODE_KEY),
    ]);

    setIpAddress(cleanedIpAddress);
    setPort(cleanedPort);
    setHasSavedSetup(true);
    setActiveTab('remote');

    const repository = createRepository(false);
    applyRepositoryUpdate({
      authStatus:
        username.trim() && password ? 'Saved credentials loaded' : 'No saved credentials',
      isDemoMode: false,
      lastMessage: `Saved ${cleanedIpAddress}:${cleanedPort}. Waiting for LinuxTV.`,
    });

    await repository.connect({
      ipAddress: cleanedIpAddress,
      password,
      port: cleanedPort,
      username: username.trim(),
    });
  };

  const clearSavedSetup = async () => {
    clearRepeatTimers();
    repositoryRef.current?.dispose();
    repositoryRef.current = null;

    await Promise.all([
      SecureStore.deleteItemAsync(HOST_KEY),
      SecureStore.deleteItemAsync(PORT_KEY),
      SecureStore.deleteItemAsync(USERNAME_KEY),
      SecureStore.deleteItemAsync(PASSWORD_KEY),
      SecureStore.deleteItemAsync(DEMO_MODE_KEY),
    ]);

    setDemoApps([]);
    setHasSavedSetup(false);
    setIpAddress('');
    setPort(DEFAULT_PORT);
    setUsername('');
    setPassword('');
    setActiveTab('remote');
    setKeyboardDraft('');
    setRepositoryState({
      ...DEFAULT_REPOSITORY_STATE,
      lastMessage: 'Saved setup removed. Enter the LinuxTV info again.',
    });
  };

  const confirmLogout = () => {
    setIsMenuVisible(false);
    Alert.alert(
      repositoryState.isDemoMode ? 'Exit demo mode?' : 'Logout?',
      repositoryState.isDemoMode
        ? 'Return to the connection screen and leave the mock device.'
        : 'This removes the saved IP address, port, username, and password from this phone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: repositoryState.isDemoMode ? 'Exit Demo' : 'Logout',
          style: 'destructive',
          onPress: () => {
            void clearSavedSetup();
          },
        },
      ]
    );
  };

  const sendAction = (action: string) => {
    repositoryRef.current?.sendAction(action);
  };

  const confirmPowerAction = (action: 'SHUTDOWN' | 'REBOOT') => {
    setIsMenuVisible(false);
    const actionLabel = action === 'SHUTDOWN' ? 'Shutdown' : 'Reboot';

    if (repositoryState.isDemoMode) {
      sendAction(action);
      return;
    }

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
    repositoryRef.current?.sendText(text);
    setKeyboardDraft('');
  };

  const sendSpecialKey = (key: 'ENTER' | 'SPACE' | 'BACKSPACE' | 'ESCAPE' | 'TAB') => {
    repositoryRef.current?.sendSpecialKey(key);
  };

  const sendPointerEvent = (
    event: 'move' | 'tap' | 'click' | 'right_click',
    payload?: { dx?: number; dy?: number }
  ) => {
    repositoryRef.current?.sendPointerEvent(event, payload);
  };

  useEffect(() => {
    let active = true;

    const loadSavedSetup = async () => {
      const [storedHost, storedPort, storedUsername, storedPassword, storedDemoMode] =
        await Promise.all([
          SecureStore.getItemAsync(HOST_KEY),
          SecureStore.getItemAsync(PORT_KEY),
          SecureStore.getItemAsync(USERNAME_KEY),
          SecureStore.getItemAsync(PASSWORD_KEY),
          SecureStore.getItemAsync(DEMO_MODE_KEY),
        ]);

      if (!active) {
        return;
      }

      const nextHost = storedHost?.trim() ?? '';
      const nextPort = storedPort?.trim() || DEFAULT_PORT;
      const nextUsername = storedUsername ?? '';
      const nextPassword = storedPassword ?? '';
      const savedDemoMode = storedDemoMode === 'true';

      setIpAddress(nextHost);
      setPort(nextPort);
      setUsername(nextUsername);
      setPassword(nextPassword);
      setIsHydrated(true);

      if (savedDemoMode) {
        setHasSavedSetup(true);
        await activateDemoMode(false);
        return;
      }

      setHasSavedSetup(Boolean(nextHost));
      setRepositoryState({
        ...DEFAULT_REPOSITORY_STATE,
        authStatus:
          nextUsername && nextPassword ? 'Saved credentials loaded' : 'No saved credentials',
        lastMessage: nextHost
          ? `Saved ${nextHost}:${nextPort}. Waiting for LinuxTV.`
          : 'Enter the LinuxTV info once to keep this remote paired.',
      });

      if (nextHost) {
        const repository = createRepository(false);
        await repository.connect({
          ipAddress: nextHost,
          password: nextPassword,
          port: nextPort,
          username: nextUsername,
        });
      }
    };

    void loadSavedSetup();

    return () => {
      active = false;
      clearRepeatTimers();
      repositoryRef.current?.dispose();
      repositoryRef.current = null;
    };
  }, []);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState: AppStateStatus) => {
      if (nextState !== 'active' || !hasSavedSetup || !isHydrated || repositoryState.isDemoMode) {
        return;
      }

      void repositoryRef.current?.connect({
        ipAddress,
        password,
        port,
        username,
      });
    });

    return () => {
      subscription.remove();
    };
  }, [hasSavedSetup, ipAddress, isHydrated, password, port, repositoryState.isDemoMode, username]);

  const showLoginScreen = !hasSavedSetup;
  const tabItems: { key: TabType; label: string }[] = [
    { key: 'remote', label: 'Remote' },
    { key: 'keyboard', label: 'Keyboard' },
    { key: 'touchpad', label: 'Touchpad' },
  ];

  const touchpadResponder = useRef(
    PanResponder.create({
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
    })
  ).current;

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        {repositoryState.isDemoMode ? (
          <View style={styles.demoBanner}>
            <Text style={styles.demoBannerText}>Demo Mode</Text>
          </View>
        ) : null}

        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <View>
              <Text style={styles.title}>LinuxTV</Text>
              {repositoryState.deviceName ? (
                <Text style={styles.deviceName}>{repositoryState.deviceName}</Text>
              ) : null}
            </View>
            <View
              style={[
                styles.statusDot,
                repositoryState.status === 'Connected'
                  ? styles.statusOnline
                  : styles.statusOffline,
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
          <View style={styles.loginContainer}>
            <Text style={styles.helperText}>Enter LinuxTV connection details</Text>
            <Text style={styles.helperSubtext}>
              Google Play reviewers can use Demo Mode without a real LinuxTV server.
            </Text>
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
            <Pressable
              style={[styles.actionButton, styles.secondaryButton]}
              onPress={() => {
                void activateDemoMode();
              }}>
              <Text style={styles.secondaryButtonText}>Skip Connection</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.remoteContainer}>
            <Text style={styles.statusMessage}>{repositoryState.lastMessage}</Text>

            {activeTab === 'remote' && (
              <ScrollView
                style={styles.remoteScroll}
                contentContainerStyle={styles.remoteScrollContent}
                showsVerticalScrollIndicator={false}>
                <View style={styles.remoteControl}>
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

                  <View style={styles.actionButtonsRow}>
                    <ControlButton
                      label="Vol -"
                      onPress={() => sendAction('VOLUME_DOWN')}
                      style={styles.actionButtonSmall}
                      textStyle={styles.actionButtonText}
                    />
                    <ControlButton
                      label="Mute"
                      onPress={() => sendAction('MUTE')}
                      style={styles.actionButtonSmall}
                      textStyle={styles.actionButtonText}
                    />
                    <ControlButton
                      label="Vol +"
                      onPress={() => sendAction('VOLUME_UP')}
                      style={styles.actionButtonSmall}
                      textStyle={styles.actionButtonText}
                    />
                  </View>
                </View>

                <View style={styles.launcherSection}>
                  <Text style={styles.launcherTitle}>Launcher</Text>
                  <Text style={styles.launcherSubtitle}>
                    {repositoryState.isDemoMode
                      ? 'Mock apps are available for Play review and demo walkthroughs.'
                      : 'Quick actions stay available while the LinuxTV session is connected.'}
                  </Text>
                  <View style={styles.launcherGrid}>
                    {(demoApps.length ? demoApps : [{ id: 'live-home', name: 'LinuxTV Home', subtitle: 'Connected device' }]).map(
                      (app) => (
                        <Pressable
                          key={app.id}
                          style={({ pressed }) => [
                            styles.launcherTile,
                            pressed && styles.pressed,
                          ]}
                          onPress={() => sendAction(`OPEN_${app.name.toUpperCase().replaceAll(' ', '_')}`)}>
                          <Text style={styles.launcherTileTitle}>{app.name}</Text>
                          <Text style={styles.launcherTileSubtitle}>{app.subtitle}</Text>
                        </Pressable>
                      )
                    )}
                  </View>
                </View>
              </ScrollView>
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
              <Text style={styles.menuItemText}>
                {repositoryState.isDemoMode ? 'Exit Demo Mode' : 'Logout'}
              </Text>
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
  demoBanner: {
    alignSelf: 'flex-start',
    backgroundColor: '#f59e0b',
    borderRadius: 999,
    marginBottom: 12,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  demoBannerText: {
    color: '#0a0e17',
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 0.4,
    textTransform: 'uppercase',
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
    flex: 1,
  },
  title: {
    color: '#f0f6fc',
    fontSize: 28,
    fontWeight: '800',
  },
  deviceName: {
    color: '#8b949e',
    fontSize: 13,
    marginTop: 2,
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
  helperText: {
    color: '#8b949e',
    fontSize: 14,
    lineHeight: 20,
    textAlign: 'center',
  },
  helperSubtext: {
    color: '#58a6ff',
    fontSize: 13,
    lineHeight: 18,
    textAlign: 'center',
    marginTop: -4,
  },
  remoteContainer: {
    flex: 1,
    justifyContent: 'space-between',
  },
  remoteScroll: {
    flex: 1,
  },
  remoteScrollContent: {
    gap: 18,
    paddingBottom: 24,
  },
  statusMessage: {
    color: '#8b949e',
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 8,
  },
  remoteControl: {
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
  launcherSection: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#11161f',
    padding: 16,
    gap: 12,
  },
  launcherTitle: {
    color: '#f0f6fc',
    fontSize: 18,
    fontWeight: '800',
  },
  launcherSubtitle: {
    color: '#8b949e',
    fontSize: 13,
    lineHeight: 18,
  },
  launcherGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  launcherTile: {
    width: '48%',
    minHeight: 86,
    borderRadius: 14,
    backgroundColor: '#1b2330',
    borderWidth: 1,
    borderColor: '#2d3748',
    padding: 14,
    justifyContent: 'space-between',
  },
  launcherTileTitle: {
    color: '#f0f6fc',
    fontSize: 16,
    fontWeight: '700',
  },
  launcherTileSubtitle: {
    color: '#8b949e',
    fontSize: 12,
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
  secondaryButton: {
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#58a6ff',
  },
  secondaryButtonText: {
    color: '#58a6ff',
    fontSize: 16,
    fontWeight: '700',
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
