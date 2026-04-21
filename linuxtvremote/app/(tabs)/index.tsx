import { useEffect, useRef, useState } from 'react';
import * as SecureStore from 'expo-secure-store';
import * as Haptics from 'expo-haptics';
import {
  Alert,
  AppState,
  AppStateStatus,
  Image as RNImage,
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
import { Ionicons } from '@expo/vector-icons';
import type { ComponentProps } from 'react';

import {
  DemoRepository,
  type AuthState,
  type ConnectionState,
  RealServerRepository,
  type RemoteRepository,
  type RepositoryState,
} from '@/lib/remote-repository';

const HOST_KEY = 'linuxtv_remote_host';
const PORT_KEY = 'linuxtv_remote_port';
const USERNAME_KEY = 'linuxtv_remote_username';
const PASSWORD_KEY = 'linuxtv_remote_password';
const DEMO_MODE_KEY = 'linuxtv_remote_demo_mode';
const SYSTEMS_KEY = 'linuxtv_remote_systems';
const ACTIVE_SYSTEM_ID_KEY = 'linuxtv_remote_active_system_id';
const DEFAULT_PORT = '8765';
const DEFAULT_KODI_PORT = '8080';
const REMOTE_REPEAT_DELAY_MS = 320;
const REMOTE_REPEAT_INTERVAL_MS = 90;

type ScreenRepositoryState = RepositoryState & {
  authStatus: AuthState;
  status: ConnectionState;
};

type TabType = 'remote' | 'keyboard' | 'touchpad' | 'apps' | 'kodi';

type KodiChannel = {
  channelid: number;
  channelnumber: string;
  label: string;
  thumbnail?: string;
};

type KodiChannelGroup = {
  channelgroupid: number | string;
  label: string;
};

type SavedSystem = {
  id: string;
  ipAddress: string;
  kodiPassword: string;
  kodiPort: string;
  kodiUsername: string;
  name: string;
  password: string;
  port: string;
  username: string;
};

const DEFAULT_REPOSITORY_STATE: ScreenRepositoryState = {
  authStatus: 'No saved credentials',
  deviceName: '',
  isDemoMode: false,
  lastAction: 'None',
  lastMessage: 'Looking for saved LinuxTV remote info',
  status: 'Disconnected',
};

const createSystemId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const buildSystemName = (name: string, ipAddress: string) => name.trim() || ipAddress.trim();

const encodeBase64 = (value: string) => {
  // Use global btoa if available (web), otherwise use manual encoding for React Native
  if (typeof globalThis.btoa !== 'undefined') {
    return globalThis.btoa(value);
  }
  
  // Fallback for React Native: manual base64 encoding
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let output = '';

  for (let index = 0; index < value.length; index += 3) {
    const byte1 = value.charCodeAt(index);
    const hasByte2 = index + 1 < value.length;
    const hasByte3 = index + 2 < value.length;
    const byte2 = hasByte2 ? value.charCodeAt(index + 1) : 0;
    const byte3 = hasByte3 ? value.charCodeAt(index + 2) : 0;

    const chunk = (byte1 << 16) | (byte2 << 8) | byte3;

    output += chars[(chunk >> 18) & 63];
    output += chars[(chunk >> 12) & 63];
    output += hasByte2 ? chars[(chunk >> 6) & 63] : '=';
    output += hasByte3 ? chars[chunk & 63] : '=';
  }

  return output;
};

const parseStoredSystems = (storedValue: string | null): SavedSystem[] => {
  if (!storedValue) {
    return [];
  }

  try {
    const parsedValue = JSON.parse(storedValue) as unknown;
    if (!Array.isArray(parsedValue)) {
      return [];
    }

    return parsedValue
      .map((entry) => {
        if (!entry || typeof entry !== 'object') {
          return null;
        }

        const candidate = entry as Partial<SavedSystem>;
        const ipAddress = candidate.ipAddress?.trim() ?? '';
        if (!ipAddress) {
          return null;
        }

        return {
          id: candidate.id?.trim() || createSystemId(),
          ipAddress,
          kodiPassword: candidate.kodiPassword ?? '',
          kodiPort: candidate.kodiPort?.trim() || DEFAULT_KODI_PORT,
          kodiUsername: candidate.kodiUsername ?? '',
          name: buildSystemName(candidate.name ?? '', ipAddress),
          password: candidate.password ?? '',
          port: candidate.port?.trim() || DEFAULT_PORT,
          username: candidate.username ?? '',
        };
      })
      .filter((entry): entry is SavedSystem => Boolean(entry));
  } catch {
    return [];
  }
};

export default function RemoteScreen() {
  const [systemName, setSystemName] = useState('');
  const [ipAddress, setIpAddress] = useState('');
  const [port, setPort] = useState(DEFAULT_PORT);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [kodiPort, setKodiPort] = useState(DEFAULT_KODI_PORT);
  const [kodiUsername, setKodiUsername] = useState('');
  const [kodiPassword, setKodiPassword] = useState('');
  const [savedSystems, setSavedSystems] = useState<SavedSystem[]>([]);
  const [activeSystemId, setActiveSystemId] = useState<string | null>(null);
  const activeSystem = savedSystems.find((system) => system.id === activeSystemId) ?? null;
  const [editingSystemId, setEditingSystemId] = useState<string | null>(null);
  const [hasSavedSetup, setHasSavedSetup] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);
  const [isMenuVisible, setIsMenuVisible] = useState(false);
  const [isSystemEditorVisible, setIsSystemEditorVisible] = useState(false);
  const [activeTab, setActiveTab] = useState<TabType>('remote');
  const [keyboardDraft, setKeyboardDraft] = useState('');
  const [volumeLevel, setVolumeLevel] = useState(50);
  const [isMuted, setIsMuted] = useState(false);
  const [serverApps, setServerApps] = useState<
    { id: string; name: string; icon?: string; kind?: string; category?: string }[]
  >([]);
  const [isAddAppVisible, setIsAddAppVisible] = useState(false);
  const [newAppName, setNewAppName] = useState('');
  const [newAppType, setNewAppType] = useState<'native' | 'web'>('native');
  const [newAppCommand, setNewAppCommand] = useState('');
  const [newAppUrl, setNewAppUrl] = useState('');
  const [kodiSearchQuery, setKodiSearchQuery] = useState('');
  const [isKodiAuthVisible, setIsKodiAuthVisible] = useState(false);
  const [kodiAuthPort, setKodiAuthPort] = useState(DEFAULT_KODI_PORT);
  const [kodiAuthUsername, setKodiAuthUsername] = useState('');
  const [kodiAuthPassword, setKodiAuthPassword] = useState('');
  const [kodiGroups, setKodiGroups] = useState<KodiChannelGroup[]>([]);
  const [kodiChannels, setKodiChannels] = useState<KodiChannel[]>([]);
  const [kodiChannelThumbnails, setKodiChannelThumbnails] = useState<Record<number, string>>({});
  const [selectedKodiGroup, setSelectedKodiGroup] = useState<KodiChannelGroup | null>(null);
  const [isKodiLoading, setIsKodiLoading] = useState(false);
  const [kodiError, setKodiError] = useState<string | null>(null);
  const [repositoryState, setRepositoryState] = useState<ScreenRepositoryState>(
    DEFAULT_REPOSITORY_STATE
  );
  const [isWifiVisible, setIsWifiVisible] = useState(false);
  const [isBluetoothVisible, setIsBluetoothVisible] = useState(false);
  const [isSoundVisible, setIsSoundVisible] = useState(false);
  const [wifiNetworks, setWifiNetworks] = useState<{ssid: string; label: string; security?: string; signal?: number}[]>([]);
  const [currentWifi, setCurrentWifi] = useState('');
  const [wifiPassword, setWifiPassword] = useState('');
  const [wifiLoading, setWifiLoading] = useState(false);
  const [wifiMessage, setWifiMessage] = useState('');
  const [bluetoothDevices, setBluetoothDevices] = useState<{mac: string; name: string; label: string; connected?: boolean; paired?: boolean}[]>([]);
  const [currentBluetooth, setCurrentBluetooth] = useState('');
  const [bluetoothLoading, setBluetoothLoading] = useState(false);
  const [bluetoothMessage, setBluetoothMessage] = useState('');
  const [soundSpeakers, setSoundSpeakers] = useState<{name: string; label: string}[]>([]);
  const [defaultSink, setDefaultSink] = useState('');
  const [soundLoading, setSoundLoading] = useState(false);
  const [soundMessage, setSoundMessage] = useState('');
  const [availableApps, setAvailableApps] = useState<Array<{id: string; name: string; icon?: string; kind?: string; category?: string}>>([]);
  const [addAppsLoading, setAddAppsLoading] = useState(false);
  const [addAppsMessage, setAddAppsMessage] = useState('');
  const [addAppMode, setAddAppMode] = useState<'custom' | 'recommended' | null>(null);
  const [selectedWifiNetwork, setSelectedWifiNetwork] = useState<{ssid: string; security: string} | null>(null);
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

  const populateFormFromSystem = (system: SavedSystem | null) => {
    setSystemName(system?.name ?? '');
    setIpAddress(system?.ipAddress ?? '');
    setPort(system?.port ?? DEFAULT_PORT);
    setUsername(system?.username ?? '');
    setPassword(system?.password ?? '');
    setKodiPort(system?.kodiPort ?? DEFAULT_KODI_PORT);
    setKodiUsername(system?.kodiUsername ?? '');
    setKodiPassword(system?.kodiPassword ?? '');
  };

  const getKodiRequestHeaders = (system: SavedSystem | null) => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    const kodiUser = system?.kodiUsername?.trim() ?? '';
    const kodiPass = system?.kodiPassword ?? '';
    if (kodiUser || kodiPass) {
      headers.Authorization = `Basic ${encodeBase64(`${kodiUser}:${kodiPass}`)}`;
    }

    return headers;
  };

  const getKodiUrl = (system: SavedSystem | null) => {
    const host = system?.ipAddress || 'localhost';
    const kodiTargetPort = system?.kodiPort?.trim() || DEFAULT_KODI_PORT;
    return `http://${host}:${kodiTargetPort}/jsonrpc`;
  };

  const getKodiImageUrl = (system: SavedSystem | null, thumbnail: string) => {
    if (!thumbnail) return '';
    const host = system?.ipAddress || 'localhost';
    const kodiTargetPort = system?.kodiPort?.trim() || DEFAULT_KODI_PORT;
    
    // Remove "image://" prefix if present
    let imagePath = thumbnail;
    if (imagePath.startsWith('image://')) {
      imagePath = imagePath.replace('image://', '');
    }
    
    // Build URL - try with credentials first
    const kodiUser = system?.kodiUsername?.trim() || '';
    const kodiPass = system?.kodiPassword || '';
    
    let baseUrl = `http://${host}:${kodiTargetPort}`;
    
    // For credentials, use base64 encoding to avoid issues with special characters
    if (kodiUser || kodiPass) {
      // Use base64 encoding for Basic Auth to handle special characters properly
      const credentials = `${kodiUser}:${kodiPass}`;
      const base64Credentials = btoa(credentials);
      // React Native Image doesn't support headers, so we must use URL-embedded credentials
      // But we need to be careful with encoding - only encode for URL safety, not double-encode
      const safeUser = encodeURIComponent(kodiUser);
      const safePass = encodeURIComponent(kodiPass);
      baseUrl = `http://${safeUser}:${safePass}@${host}:${kodiTargetPort}`;
    }
    
    return `${baseUrl}/image/${encodeURIComponent(imagePath)}`;
  };

  const openKodiAuthModal = () => {
    setKodiAuthPort(activeSystem?.kodiPort ?? DEFAULT_KODI_PORT);
    setKodiAuthUsername(activeSystem?.kodiUsername ?? '');
    setKodiAuthPassword(activeSystem?.kodiPassword ?? '');
    setIsKodiAuthVisible(true);
  };

  const persistSystems = async (systems: SavedSystem[], nextActiveSystemId?: string | null) => {
    const activeId =
      nextActiveSystemId === undefined
        ? activeSystemId
        : nextActiveSystemId;
    const activeSystem = systems.find((system) => system.id === activeId) ?? null;

    if (systems.length) {
      await SecureStore.setItemAsync(SYSTEMS_KEY, JSON.stringify(systems));
    } else {
      await SecureStore.deleteItemAsync(SYSTEMS_KEY);
    }

    if (activeSystem) {
      await Promise.all([
        SecureStore.setItemAsync(ACTIVE_SYSTEM_ID_KEY, activeSystem.id),
        SecureStore.setItemAsync(HOST_KEY, activeSystem.ipAddress),
        SecureStore.setItemAsync(PORT_KEY, activeSystem.port),
        SecureStore.setItemAsync(USERNAME_KEY, activeSystem.username),
        SecureStore.setItemAsync(PASSWORD_KEY, activeSystem.password),
      ]);
    } else {
      await Promise.all([
        SecureStore.deleteItemAsync(ACTIVE_SYSTEM_ID_KEY),
        SecureStore.deleteItemAsync(HOST_KEY),
        SecureStore.deleteItemAsync(PORT_KEY),
        SecureStore.deleteItemAsync(USERNAME_KEY),
        SecureStore.deleteItemAsync(PASSWORD_KEY),
      ]);
    }
  };

  const connectToSystem = async (system: SavedSystem) => {
    const repository = createRepository(false);
    applyRepositoryUpdate({
      authStatus:
        system.username.trim() && system.password
          ? 'Saved credentials loaded'
          : 'No saved credentials',
      isDemoMode: false,
      lastMessage: `Saved ${system.ipAddress}:${system.port}. Waiting for LinuxTV.`,
    });

    await repository.connect({
      ipAddress: system.ipAddress,
      password: system.password,
      port: system.port,
      username: system.username,
    });
  };

  const activateDemoMode = async (persist = true) => {
    const repository = createRepository(true);
    if (persist) {
      await Promise.all([
        SecureStore.setItemAsync(DEMO_MODE_KEY, 'true'),
        persistSystems([], null),
      ]);
    }
    setSavedSystems([]);
    setActiveSystemId(null);
    populateFormFromSystem(null);
    setHasSavedSetup(true);
    setActiveTab('remote');
    setKeyboardDraft('');
    await repository.connect();
  };

  const switchToSystem = async (system: SavedSystem, persistActive = true) => {
    clearRepeatTimers();
    setIsMenuVisible(false);
    setHasSavedSetup(true);
    setActiveSystemId(system.id);
    populateFormFromSystem(system);
    setActiveTab('remote');
    setKeyboardDraft('');

    if (persistActive) {
      await Promise.all([
        SecureStore.deleteItemAsync(DEMO_MODE_KEY),
        persistSystems(savedSystems, system.id),
      ]);
    }

    await connectToSystem(system);
  };

  const resetEditorToActiveSystem = () => {
    const activeSystem = savedSystems.find((system) => system.id === activeSystemId) ?? null;
    setEditingSystemId(activeSystem?.id ?? null);
    populateFormFromSystem(activeSystem);
  };

  const openAddSystemEditor = () => {
    setIsMenuVisible(false);
    setEditingSystemId(null);
    populateFormFromSystem(null);
    setIsSystemEditorVisible(true);
  };

  const openEditSystemEditor = () => {
    setIsMenuVisible(false);
    resetEditorToActiveSystem();
    setIsSystemEditorVisible(true);
  };

  const saveSystemAndConnect = async () => {
    const cleanedIpAddress = ipAddress.trim();
    const cleanedPort = port.trim() || DEFAULT_PORT;
    const cleanedUsername = username.trim();
    const cleanedKodiPort = kodiPort.trim() || DEFAULT_KODI_PORT;
    const cleanedKodiUsername = kodiUsername.trim();
    const cleanedName = buildSystemName(systemName, cleanedIpAddress);

    if (!cleanedIpAddress) {
      Alert.alert('Missing address', 'Enter the LinuxTV IP address first.');
      return;
    }

    const systemId = editingSystemId ?? createSystemId();
    const nextSystem: SavedSystem = {
      id: systemId,
      ipAddress: cleanedIpAddress,
      kodiPassword,
      kodiPort: cleanedKodiPort,
      kodiUsername: cleanedKodiUsername,
      name: cleanedName,
      password,
      port: cleanedPort,
      username: cleanedUsername,
    };

    const existingIndex = savedSystems.findIndex((system) => system.id === systemId);
    const nextSystems =
      existingIndex >= 0
        ? savedSystems.map((system) => (system.id === systemId ? nextSystem : system))
        : [...savedSystems, nextSystem];

    setSavedSystems(nextSystems);
    setEditingSystemId(systemId);
    setIsSystemEditorVisible(false);
    setHasSavedSetup(true);

    await Promise.all([
      SecureStore.deleteItemAsync(DEMO_MODE_KEY),
      persistSystems(nextSystems, systemId),
    ]);

    await switchToSystem(nextSystem, false);
  };

  const clearSavedSetup = async () => {
    clearRepeatTimers();
    repositoryRef.current?.dispose();
    repositoryRef.current = null;

    await Promise.all([
      persistSystems([], null),
      SecureStore.deleteItemAsync(DEMO_MODE_KEY),
    ]);

    setSavedSystems([]);
    setActiveSystemId(null);
    setEditingSystemId(null);
    setHasSavedSetup(false);
    setIsMenuVisible(false);
    setIsSystemEditorVisible(false);
    setActiveTab('remote');
    setKeyboardDraft('');
    populateFormFromSystem(null);
    setRepositoryState({
      ...DEFAULT_REPOSITORY_STATE,
      lastMessage: 'Saved systems removed. Enter the LinuxTV info again.',
    });
  };

  const removeSystem = async (systemId: string) => {
    const nextSystems = savedSystems.filter((system) => system.id !== systemId);
    const nextActiveSystem = nextSystems[0] ?? null;

    setIsMenuVisible(false);
    setIsSystemEditorVisible(false);

    if (!nextActiveSystem) {
      await clearSavedSetup();
      return;
    }

    setSavedSystems(nextSystems);
    await Promise.all([
      SecureStore.deleteItemAsync(DEMO_MODE_KEY),
      persistSystems(nextSystems, nextActiveSystem.id),
    ]);
    await switchToSystem(nextActiveSystem, false);
  };

  const confirmRemoveActiveSystem = () => {
    const activeSystem = savedSystems.find((system) => system.id === activeSystemId);
    if (!activeSystem) {
      return;
    }

    Alert.alert(
      'Remove system?',
      savedSystems.length === 1
        ? 'This will remove the last saved LinuxTV system from this phone.'
        : `Remove ${activeSystem.name} from saved systems?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: () => {
            void removeSystem(activeSystem.id);
          },
        },
      ]
    );
  };

  const confirmLogout = () => {
    setIsMenuVisible(false);
    Alert.alert(
      repositoryState.isDemoMode ? 'Exit demo mode?' : 'Remove all saved systems?',
      repositoryState.isDemoMode
        ? 'Return to the connection screen and leave the mock device.'
        : 'This removes every saved LinuxTV system, including usernames and passwords, from this phone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: repositoryState.isDemoMode ? 'Exit Demo' : 'Remove All',
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

  const sendSettingsRequest = (type: string, payload: Record<string, any> = {}) => {
    repositoryRef.current?.sendSettingsRequest(type, payload);
  };

  // WiFi handlers
  const fetchWifiNetworks = () => {
    setWifiLoading(true);
    setWifiMessage('');
    setSelectedWifiNetwork(null);
    sendSettingsRequest('get_wifi');
  };

  const selectWifiNetwork = (ssid: string, security: string) => {
    setSelectedWifiNetwork({ ssid, security });
    if (!security || security.toLowerCase() === 'open') {
      // Connect immediately for open networks
      setWifiLoading(true);
      setWifiMessage('Connecting...');
      sendSettingsRequest('connect_wifi', { ssid, password: '', security });
    } else {
      setWifiPassword('');
      setWifiMessage(`Enter password for ${ssid}`);
    }
  };

  const connectToSelectedWifi = () => {
    if (!selectedWifiNetwork) {
      setWifiMessage('Please select a network first.');
      return;
    }
    if (selectedWifiNetwork.security && selectedWifiNetwork.security.toLowerCase() !== 'open' && !wifiPassword) {
      setWifiMessage('Please enter the Wi-Fi password.');
      return;
    }
    setWifiLoading(true);
    setWifiMessage('Connecting...');
    sendSettingsRequest('connect_wifi', { 
      ssid: selectedWifiNetwork.ssid, 
      password: wifiPassword, 
      security: selectedWifiNetwork.security 
    });
  };

  // Bluetooth handlers
  const fetchBluetoothDevices = () => {
    setBluetoothLoading(true);
    setBluetoothMessage('');
    sendSettingsRequest('get_bluetooth');
  };

  const connectToBluetooth = (mac: string) => {
    if (!mac) {
      setBluetoothMessage('Please select a device.');
      return;
    }
    setBluetoothLoading(true);
    setBluetoothMessage('Connecting...');
    sendSettingsRequest('connect_bluetooth', { mac });
  };

  const removeBluetoothDevice = (mac: string) => {
    if (!mac) {
      setBluetoothMessage('Please select a device.');
      return;
    }
    setBluetoothLoading(true);
    setBluetoothMessage('Removing...');
    sendSettingsRequest('remove_bluetooth', { mac });
  };

  // Sound handlers
  const fetchSoundDevices = () => {
    setSoundLoading(true);
    setSoundMessage('');
    sendSettingsRequest('get_sound');
  };

  const fetchAvailableApps = () => {
    setAddAppsLoading(true);
    setAddAppsMessage('');
    sendAction('GET_APPS');
  };

  const addAppToSystem = (appId: string, appName: string, kind: string) => {
    setAddAppsLoading(true);
    setAddAppsMessage(`Adding ${appName}...`);
    sendSettingsRequest('add_app', { id: appId, name: appName, kind });
  };

  const fetchKodiImage = (channelId: number, thumbnailPath: string) => {
    // Remove image:// prefix if present
    let imagePath = thumbnailPath;
    if (imagePath.startsWith('image://')) {
      imagePath = imagePath.replace('image://', '');
    }
    
    // Request image through WebSocket (desktop will handle auth)
    repositoryRef.current?.sendSettingsRequest('get_kodi_image', { path: imagePath });
  };

  const showCustomApp = () => {
    setAddAppMode('custom');
    setIsAddAppVisible(true);
    setAvailableApps([]);
  };

  const showRecommendedApps = () => {
    setAddAppMode('recommended');
    setIsAddAppVisible(false);
    fetchAvailableApps();
  };

  const setSoundDevice = (sink: string) => {
    if (!sink) {
      setSoundMessage('Please select an audio device.');
      return;
    }
    setSoundLoading(true);
    setSoundMessage('Setting default device...');
    sendSettingsRequest('set_sound', { sink });
  };

  const launchApp = (appId: string) => {
    sendAction(`LAUNCH_APP:${appId}`);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
  };

  const fetchApps = () => {
    // Request apps from server
    sendAction('GET_APPS');
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
  };

  const saveKodiAuthForActiveSystem = async () => {
    if (!activeSystem) {
      return null;
    }

    const nextSystem: SavedSystem = {
      ...activeSystem,
      kodiPassword: kodiAuthPassword,
      kodiPort: kodiAuthPort.trim() || DEFAULT_KODI_PORT,
      kodiUsername: kodiAuthUsername.trim(),
    };

    const nextSystems = savedSystems.map((system) =>
      system.id === activeSystem.id ? nextSystem : system
    );

    setSavedSystems(nextSystems);
    setKodiPort(nextSystem.kodiPort);
    setKodiUsername(nextSystem.kodiUsername);
    setKodiPassword(nextSystem.kodiPassword);
    await persistSystems(nextSystems, nextSystem.id);
    setIsKodiAuthVisible(false);

    return nextSystem;
  };

  const fetchKodiGroups = async (systemOverride?: SavedSystem | null) => {
    setIsKodiLoading(true);
    setKodiError(null);

    try {
      const kodiSystem = systemOverride ?? activeSystem;
      const kodiUrl = getKodiUrl(kodiSystem);
      const response = await fetch(kodiUrl, {
        method: 'POST',
        headers: getKodiRequestHeaders(kodiSystem),
        body: JSON.stringify({
          jsonrpc: '2.0',
          method: 'PVR.GetChannelGroups',
          params: { channeltype: 'tv' },
          id: 1,
        }),
      });

      if (response.status === 401) {
        openKodiAuthModal();
        throw new Error('Kodi authentication failed');
      }

      if (!response.ok) {
        throw new Error('Failed to connect to Kodi');
      }

      const data = await response.json();
      const groups = (data?.result?.channelgroups || []) as KodiChannelGroup[];
      setSelectedKodiGroup(null);
      setKodiChannels([]);
      setKodiGroups(groups);

      if (groups.length === 0) {
        setKodiError('No channel folders found. Make sure PVR channel groups are available in Kodi.');
      }
    } catch (error) {
      console.error('Error fetching Kodi groups:', error);
      const message =
        error instanceof Error && error.message === 'Kodi authentication failed'
          ? 'Kodi rejected the username or password. Update the Kodi credentials in the system settings.'
          : 'Could not connect to Kodi. Make sure Kodi is running, the web server is enabled, and the Kodi username/password are correct.';
      setKodiError(message);
      setKodiGroups([]);
      setKodiChannels([]);
      setSelectedKodiGroup(null);
    } finally {
      setIsKodiLoading(false);
    }
  };

  const fetchKodiChannels = async (
    systemOverride?: SavedSystem | null,
    groupOverride?: KodiChannelGroup | null
  ) => {
    setIsKodiLoading(true);
    setKodiError(null);
    
    try {
      const kodiSystem = systemOverride ?? activeSystem;
      const kodiGroup = groupOverride ?? selectedKodiGroup;
      const kodiUrl = getKodiUrl(kodiSystem);
      const kodiHost = kodiSystem?.ipAddress || 'localhost';
      const kodiPort = kodiSystem?.kodiPort?.trim() || DEFAULT_KODI_PORT;
      
      const payload = {
        jsonrpc: '2.0',
        method: 'PVR.GetChannels',
        params: {
          channelgroupid: kodiGroup?.channelgroupid ?? 'alltv',
          properties: ['thumbnail', 'channelnumber', 'hidden', 'locked', 'lastplayed'],
        },
        id: 1,
      };
      
      const response = await fetch(kodiUrl, {
        method: 'POST',
        headers: getKodiRequestHeaders(kodiSystem),
        body: JSON.stringify(payload),
      });
      
      if (response.status === 401) {
        openKodiAuthModal();
        throw new Error('Kodi authentication failed');
      }

      if (!response.ok) {
        throw new Error('Failed to connect to Kodi');
      }
      
      const data = await response.json();
      const channels = (data?.result?.channels || []) as KodiChannel[];
      setKodiChannels(channels);
      
      if (channels.length === 0) {
        setKodiError(
          kodiGroup
            ? `No channels found in ${kodiGroup.label}.`
            : 'No channels found. Make sure PVR is configured in Kodi.'
        );
      }
    } catch (error) {
      console.error('Error fetching Kodi channels:', error);
      const message =
        error instanceof Error && error.message === 'Kodi authentication failed'
          ? 'Kodi rejected the username or password. Update the Kodi credentials in the system settings.'
          : 'Could not connect to Kodi. Make sure Kodi is running, the web server is enabled, and the Kodi username/password are correct.';
      setKodiError(message);
      setKodiChannels([]);
    } finally {
      setIsKodiLoading(false);
    }
  };

  const playKodiChannel = async (channelId: number, channelName: string) => {
    try {
      const kodiUrl = getKodiUrl(activeSystem);
      
      const payload = {
        jsonrpc: "2.0",
        method: "Player.Open",
        params: {
          item: { channelid: channelId }
        },
        id: 1
      };
      
      const response = await fetch(kodiUrl, {
        method: 'POST',
        headers: getKodiRequestHeaders(activeSystem),
        body: JSON.stringify(payload),
      });

      if (response.status === 401) {
        openKodiAuthModal();
        throw new Error('Kodi authentication failed');
      }
      
      if (response.ok) {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        console.log(`Playing channel: ${channelName}`);
      } else {
        Alert.alert('Error', 'Failed to play channel');
      }
    } catch (error) {
      console.error('Error playing channel:', error);
      Alert.alert(
        'Error',
        error instanceof Error && error.message === 'Kodi authentication failed'
          ? 'Kodi rejected the username or password for this system.'
          : 'Could not connect to Kodi'
      );
    }
  };

  const checkKodiAvailability = async () => {
    try {
      const kodiUrl = getKodiUrl(activeSystem);
      
      const payload = {
        jsonrpc: "2.0",
        method: "JSONRPC.Ping",
        id: 1
      };
      
      const fetchPromise = fetch(kodiUrl, {
        method: 'POST',
        headers: getKodiRequestHeaders(activeSystem),
        body: JSON.stringify(payload),
      });
      
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => reject(new Error('Timeout')), 2000);
      });
      
      const response = await Promise.race([fetchPromise, timeoutPromise]) as Response;
      
      if (response.ok) {
        const data = await response.json();
        if (data.result === 'pong') {
          return;
        }
      }
    } catch {
      return;
    }
  };

  const addNewApp = () => {
    if (!newAppName.trim()) {
      Alert.alert('Missing name', 'Please enter an app name.');
      return;
    }

    if (newAppType === 'native' && !newAppCommand.trim()) {
      Alert.alert('Missing command', 'Please enter the app command.');
      return;
    }

    if (newAppType === 'web' && !newAppUrl.trim()) {
      Alert.alert('Missing URL', 'Please enter the app URL.');
      return;
    }

    const payload = {
      type: 'add_app',
      kind: newAppType,
      name: newAppName.trim(),
      ...(newAppType === 'native' ? { command: newAppCommand.trim() } : { url: newAppUrl.trim() }),
    };

    if (repositoryRef.current) {
      repositoryRef.current.addApp({
        type: newAppType,
        name: newAppName.trim(),
        command: newAppType === 'native' ? newAppCommand.trim() : undefined,
        url: newAppType === 'web' ? newAppUrl.trim() : undefined,
      });
    }
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    
    // Reset form
    setNewAppName('');
    setNewAppCommand('');
    setNewAppUrl('');
    setIsAddAppVisible(false);
    
    Alert.alert('App Added', 'The app has been added to LinuxTV. Refresh the list to see it.');
    
    // Auto refresh after adding
    setTimeout(() => fetchApps(), 1000);
  };

  const removeApp = (appId: string, appName: string) => {
    Alert.alert(
      'Remove App',
      `Are you sure you want to remove "${appName}"?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: () => {
            if (repositoryRef.current) {
              repositoryRef.current.removeApp(appId);
            }
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            
            Alert.alert('App Removed', `"${appName}" has been removed.`);
            
            // Auto refresh after removing
            setTimeout(() => fetchApps(), 1000);
          },
        },
      ]
    );
  };

  const adjustVolume = (direction: 'up' | 'down') => {
    if (direction === 'up') {
      setVolumeLevel(prev => Math.min(prev + 5, 100));
      sendAction('VOLUME_UP');
    } else {
      setVolumeLevel(prev => Math.max(prev - 5, 0));
      sendAction('VOLUME_DOWN');
    }
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
  };

  const toggleMute = () => {
    // Server handles MUTE as a toggle, so just send MUTE action
    sendAction('MUTE');
    setIsMuted(!isMuted);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
  };

  const confirmPowerAction = (action: 'SHUTDOWN' | 'REBOOT' | 'SLEEP') => {
    setIsMenuVisible(false);
    const actionLabel = action === 'SHUTDOWN' ? 'Shutdown' : action === 'REBOOT' ? 'Reboot' : 'Sleep';

    if (repositoryState.isDemoMode) {
      sendAction(action);
      return;
    }

    const message =
      action === 'SHUTDOWN'
        ? 'Shut down the LinuxTV system now?'
        : action === 'REBOOT'
        ? 'Reboot the LinuxTV system now?'
        : 'Put the LinuxTV system to sleep?';

    Alert.alert(actionLabel, message, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: actionLabel,
        style: action === 'SLEEP' ? 'default' : 'destructive',
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
      const [
        storedSystemsValue,
        storedActiveSystemId,
        storedHost,
        storedPort,
        storedUsername,
        storedPassword,
        storedDemoMode,
      ] = await Promise.all([
        SecureStore.getItemAsync(SYSTEMS_KEY),
        SecureStore.getItemAsync(ACTIVE_SYSTEM_ID_KEY),
        SecureStore.getItemAsync(HOST_KEY),
        SecureStore.getItemAsync(PORT_KEY),
        SecureStore.getItemAsync(USERNAME_KEY),
        SecureStore.getItemAsync(PASSWORD_KEY),
        SecureStore.getItemAsync(DEMO_MODE_KEY),
      ]);

      if (!active) {
        return;
      }

      const savedDemoMode = storedDemoMode === 'true';
      let nextSystems = parseStoredSystems(storedSystemsValue);

      if (!nextSystems.length && storedHost?.trim()) {
        const migratedSystem: SavedSystem = {
          id: createSystemId(),
          ipAddress: storedHost.trim(),
          kodiPassword: '',
          kodiPort: DEFAULT_KODI_PORT,
          kodiUsername: '',
          name: buildSystemName('', storedHost.trim()),
          password: storedPassword ?? '',
          port: storedPort?.trim() || DEFAULT_PORT,
          username: storedUsername ?? '',
        };
        nextSystems = [migratedSystem];
        await persistSystems(nextSystems, migratedSystem.id);
      }

      setSavedSystems(nextSystems);
      setIsHydrated(true);

      if (savedDemoMode) {
        setHasSavedSetup(true);
        await activateDemoMode(false);
        return;
      }

      const nextActiveSystem =
        nextSystems.find((system) => system.id === storedActiveSystemId) ?? nextSystems[0] ?? null;

      setActiveSystemId(nextActiveSystem?.id ?? null);
      populateFormFromSystem(nextActiveSystem);
      setHasSavedSetup(Boolean(nextActiveSystem));
      setRepositoryState({
        ...DEFAULT_REPOSITORY_STATE,
        authStatus:
          nextActiveSystem?.username.trim() && nextActiveSystem.password
            ? 'Saved credentials loaded'
            : 'No saved credentials',
        lastMessage: nextActiveSystem
          ? `Saved ${nextActiveSystem.ipAddress}:${nextActiveSystem.port}. Waiting for LinuxTV.`
          : 'Enter the LinuxTV info once to keep this remote paired.',
      });

      if (nextActiveSystem) {
        if (nextActiveSystem.id !== storedActiveSystemId) {
          await persistSystems(nextSystems, nextActiveSystem.id);
        }
        await connectToSystem(nextActiveSystem);
      }
    };

    void loadSavedSetup();

    return () => {
      active = false;
      clearRepeatTimers();
      repositoryRef.current?.dispose();
      repositoryRef.current = null;
    };
    // This hydrates saved state once on mount, including migration from legacy keys.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update server apps when repository state changes
  useEffect(() => {
    if (repositoryState.appsList && repositoryState.appsList.length > 0) {
      setServerApps(repositoryState.appsList);
    }
  }, [repositoryState.appsList]);

  // Update WiFi state when repository state changes
  useEffect(() => {
    if (repositoryState.wifiNetworks !== undefined) {
      setWifiNetworks(repositoryState.wifiNetworks || []);
    }
    if (repositoryState.currentWifi !== undefined) {
      setCurrentWifi(repositoryState.currentWifi || '');
    }
    if (repositoryState.wifiMessage !== undefined) {
      setWifiMessage(repositoryState.wifiMessage || '');
      setWifiLoading(false);
    }
  }, [repositoryState.wifiNetworks, repositoryState.currentWifi, repositoryState.wifiMessage]);

  // Update Bluetooth state when repository state changes
  useEffect(() => {
    if (repositoryState.bluetoothDevices !== undefined) {
      setBluetoothDevices(repositoryState.bluetoothDevices || []);
    }
    if (repositoryState.currentBluetooth !== undefined) {
      setCurrentBluetooth(repositoryState.currentBluetooth || '');
    }
    if (repositoryState.bluetoothMessage !== undefined) {
      setBluetoothMessage(repositoryState.bluetoothMessage || '');
      setBluetoothLoading(false);
    }
  }, [repositoryState.bluetoothDevices, repositoryState.currentBluetooth, repositoryState.bluetoothMessage]);

  // Update Sound state when repository state changes
  useEffect(() => {
    if (repositoryState.soundSpeakers !== undefined) {
      setSoundSpeakers(repositoryState.soundSpeakers || []);
    }
    if (repositoryState.defaultSink !== undefined) {
      setDefaultSink(repositoryState.defaultSink || '');
    }
    if (repositoryState.soundMessage !== undefined) {
      setSoundMessage(repositoryState.soundMessage || '');
      setSoundLoading(false);
    }
    if (repositoryState.addAppsMessage !== undefined) {
      setAddAppsMessage(repositoryState.addAppsMessage || '');
      setAddAppsLoading(false);
    }
    // Handle Kodi image response
    if (repositoryState.kodiImage && repositoryState.kodiImagePath) {
      // Find the channel ID that matches this path
      const matchingChannel = kodiChannels.find(ch => {
        let chPath = ch.thumbnail || '';
        if (chPath.startsWith('image://')) {
          chPath = chPath.replace('image://', '');
        }
        return chPath === repositoryState.kodiImagePath;
      });
      
      if (matchingChannel) {
        setKodiChannelThumbnails(prev => ({
          ...prev,
          [matchingChannel.channelid]: repositoryState.kodiImage!,
        }));
      }
    }
  }, [repositoryState.soundSpeakers, repositoryState.defaultSink, repositoryState.soundMessage, repositoryState.addAppsMessage, repositoryState.kodiImage, repositoryState.kodiImagePath, kodiChannels]);

  // Fetch Kodi images when channels are loaded
  useEffect(() => {
    if (kodiChannels.length > 0) {
      kodiChannels.forEach(channel => {
        if (channel.thumbnail && !kodiChannelThumbnails[channel.channelid]) {
          fetchKodiImage(channel.channelid, channel.thumbnail);
        }
      });
    }
  }, [kodiChannels]);

  // Update available apps when repository state changes
  useEffect(() => {
    if (repositoryState.appsList && repositoryState.appsList.length > 0) {
      setAvailableApps(repositoryState.appsList);
      setAddAppsLoading(false);
    }
  }, [repositoryState.appsList]);

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

  useEffect(() => {
    if (repositoryState.isDemoMode || !activeSystem?.ipAddress) {
      return;
    }

    void checkKodiAvailability();
    // This probe should rerun when the selected system or Kodi credentials change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeSystem?.id,
    activeSystem?.ipAddress,
    activeSystem?.kodiPassword,
    activeSystem?.kodiPort,
    activeSystem?.kodiUsername,
    repositoryState.isDemoMode,
  ]);

  useEffect(() => {
    if (activeTab !== 'kodi' || repositoryState.isDemoMode || !activeSystem?.ipAddress) {
      return;
    }

    if (!selectedKodiGroup && kodiGroups.length === 0 && !isKodiLoading) {
      void fetchKodiGroups();
    }
    // This is an entry-point fetch for the Kodi browser.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, activeSystem?.id, repositoryState.isDemoMode]);

  const showLoginScreen = !hasSavedSetup;
  const normalizedKodiSearchQuery = kodiSearchQuery.trim().toLowerCase();
  const filteredKodiGroups = normalizedKodiSearchQuery
    ? kodiGroups.filter((group) => group.label.toLowerCase().includes(normalizedKodiSearchQuery))
    : kodiGroups;
  const filteredKodiChannels = normalizedKodiSearchQuery
    ? kodiChannels.filter((channel) => {
        const channelNumber = String(channel.channelnumber ?? '');
        return (
          channel.label.toLowerCase().includes(normalizedKodiSearchQuery) ||
          channelNumber.toLowerCase().includes(normalizedKodiSearchQuery)
        );
      })
    : kodiChannels;
  const tabItems: { key: TabType; label: string; icon: ComponentProps<typeof Ionicons>['name'] }[] = [
    { key: 'remote', label: 'Remote', icon: 'phone-portrait-outline' },
    { key: 'apps', label: 'Apps', icon: 'grid' },
    { key: 'kodi', label: 'Kodi', icon: 'play-circle' },
    { key: 'keyboard', label: 'Keyboard', icon: 'text' },
    { key: 'touchpad', label: 'Touchpad', icon: 'hand-left' },
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
            <View style={styles.headerTextWrap}>
              <Text style={styles.title}>LinuxTV</Text>
              <View style={styles.headerMetaRow}>
                <Text style={styles.deviceName}>
                  {repositoryState.isDemoMode
                    ? 'Mock remote session'
                    : activeSystem?.name || repositoryState.deviceName || 'No system selected'}
                </Text>
                {!showLoginScreen ? (
                  <Text style={styles.headerStatusText} numberOfLines={1}>
                    {repositoryState.lastMessage}
                  </Text>
                ) : null}
              </View>
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
            <View style={styles.loginHeader}>
              <Ionicons name="tv" size={64} color="#58a6ff" />
              <Text style={styles.helperText}>Add your first LinuxTV system</Text>
              <Text style={styles.helperSubtext}>
                Save multiple systems here, then switch between them from the settings gear.
              </Text>
            </View>
            <TextInput
              value={systemName}
              onChangeText={setSystemName}
              placeholder="System name"
              placeholderTextColor="#8b949e"
              autoCapitalize="words"
              autoCorrect={false}
              style={styles.input}
            />
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
            <Text style={styles.formSectionLabel}>Kodi web server login</Text>
            <View style={styles.addressRow}>
              <TextInput
                value={kodiPort}
                onChangeText={setKodiPort}
                placeholder="Kodi port"
                placeholderTextColor="#8b949e"
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="number-pad"
                style={[styles.input, styles.portInput]}
              />
            </View>
            <TextInput
              value={kodiUsername}
              onChangeText={setKodiUsername}
              placeholder="Kodi username"
              placeholderTextColor="#8b949e"
              autoCapitalize="none"
              autoCorrect={false}
              style={styles.input}
            />
            <TextInput
              value={kodiPassword}
              onChangeText={setKodiPassword}
              placeholder="Kodi password"
              placeholderTextColor="#8b949e"
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              style={styles.input}
            />
            <Pressable
              style={[styles.actionButton, styles.primaryButton]}
              onPress={saveSystemAndConnect}>
              <Text style={styles.primaryButtonText}>Save & Connect</Text>
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
            {activeTab === 'remote' && (
              <ScrollView
                style={styles.remoteScroll}
                contentContainerStyle={styles.remoteScrollContent}
                showsVerticalScrollIndicator={false}>
                <View style={styles.remoteControl}>
                  {/* Modern D-Pad */}
                  <View style={styles.dpadContainer}>
                    <View style={styles.dpadCircle}>
                      {/* Top Button */}
                      <Pressable
                        style={({ pressed }) => [styles.dpadButton, styles.dpadTop, pressed && styles.pressed]}
                        onPressIn={() => {
                          createRepeatingActionHandlers('UP').onPressIn();
                          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                        }}
                        onPressOut={() => {
                          createRepeatingActionHandlers('UP').onPressOut();
                        }}
                        onPress={() => sendAction('UP')}>
                        <Ionicons name="caret-up" size={36} color="#f0f6fc" />
                      </Pressable>
                      
                      {/* Left Button */}
                      <Pressable
                        style={({ pressed }) => [styles.dpadButton, styles.dpadLeft, pressed && styles.pressed]}
                        onPressIn={() => {
                          createRepeatingActionHandlers('LEFT').onPressIn();
                          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                        }}
                        onPressOut={() => {
                          createRepeatingActionHandlers('LEFT').onPressOut();
                        }}
                        onPress={() => sendAction('LEFT')}>
                        <Ionicons name="caret-back" size={36} color="#f0f6fc" />
                      </Pressable>
                      
                      {/* Center OK Button */}
                      <Pressable
                        style={({ pressed }) => [styles.okButton, pressed && styles.pressedOk]}
                        onPress={() => {
                          sendAction('SELECT');
                          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                        }}>
                        <Text style={styles.okButtonText}>OK</Text>
                      </Pressable>
                      
                      {/* Right Button */}
                      <Pressable
                        style={({ pressed }) => [styles.dpadButton, styles.dpadRight, pressed && styles.pressed]}
                        onPressIn={() => {
                          createRepeatingActionHandlers('RIGHT').onPressIn();
                          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                        }}
                        onPressOut={() => {
                          createRepeatingActionHandlers('RIGHT').onPressOut();
                        }}
                        onPress={() => sendAction('RIGHT')}>
                        <Ionicons name="caret-forward" size={36} color="#f0f6fc" />
                      </Pressable>
                      
                      {/* Bottom Button */}
                      <Pressable
                        style={({ pressed }) => [styles.dpadButton, styles.dpadBottom, pressed && styles.pressed]}
                        onPressIn={() => {
                          createRepeatingActionHandlers('DOWN').onPressIn();
                          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                        }}
                        onPressOut={() => {
                          createRepeatingActionHandlers('DOWN').onPressOut();
                        }}
                        onPress={() => sendAction('DOWN')}>
                        <Ionicons name="caret-down" size={36} color="#f0f6fc" />
                      </Pressable>
                    </View>
                  </View>

                  {/* Navigation Buttons */}
                  <View style={styles.actionButtonsRow}>
                    <ControlButton
                      icon="arrow-back"
                      label="Back"
                      onPress={() => {
                        sendAction('BACK');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.actionButtonSmall}
                      textStyle={styles.actionButtonText}
                    />
                    <ControlButton
                      icon="home"
                      label="Home"
                      onPress={() => {
                        sendAction('HOME');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.actionButtonSmall}
                      textStyle={styles.actionButtonText}
                    />
                    <ControlButton
                      icon="menu"
                      label="Menu"
                      onPress={() => {
                        sendAction('MENU');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.actionButtonSmall}
                      textStyle={styles.actionButtonText}
                    />
                    <ControlButton
                      icon="expand"
                      label="Fullscreen"
                      onPress={() => {
                        sendAction('TOGGLE_FULLSCREEN');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                      }}
                      style={[styles.actionButtonSmall, styles.fullscreenButtonSmall]}
                      textStyle={styles.fullscreenButtonTextSmall}
                    />
                  </View>

                  {/* Media Controls */}
                  <View style={styles.actionButtonsRow}>
                    <ControlButton
                      icon="close"
                      label="Close"
                      onPress={() => {
                        sendAction('CLOSE_APP');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={[styles.actionButtonSmall, styles.closeButtonSmall]}
                      textStyle={styles.closeButtonTextSmall}
                    />
                    <ControlButton
                      icon={repositoryState.lastAction === 'PLAY_PAUSE' ? "pause" : "play"}
                      label="Play"
                      onPress={() => {
                        sendAction('PLAY_PAUSE');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                      }}
                      style={[styles.actionButtonSmall, styles.playButtonSmall]}
                      textStyle={styles.playButtonTextSmall}
                    />
                    <ControlButton
                      icon="information-circle"
                      label="Info"
                      onPress={() => {
                        sendAction('INFO');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.actionButtonSmall}
                      textStyle={styles.actionButtonText}
                    />
                  </View>

                  {/* Media Track Controls */}
                  <View style={styles.actionButtonsRow}>
                    <ControlButton
                      icon="play-skip-back"
                      label="Previous"
                      onPress={() => {
                        sendAction('PREVIOUS_TRACK');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.actionButtonSmall}
                      textStyle={styles.actionButtonText}
                    />
                    <ControlButton
                      icon="stop"
                      label="Stop"
                      onPress={() => {
                        sendAction('STOP_MEDIA');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                      }}
                      style={styles.actionButtonSmall}
                      textStyle={styles.actionButtonText}
                    />
                    <ControlButton
                      icon="play-skip-forward"
                      label="Next"
                      onPress={() => {
                        sendAction('NEXT_TRACK');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.actionButtonSmall}
                      textStyle={styles.actionButtonText}
                    />
                  </View>

                  {/* Volume Controls */}
                  <View style={styles.volumeContainer}>
                    <View style={styles.volumeSliderRow}>
                      <Ionicons name="volume-low" size={24} color="#8b949e" />
                      <View style={styles.sliderContainer}>
                        <View style={styles.sliderTrack}>
                          <View style={[styles.sliderFill, { width: `${volumeLevel}%` }]} />
                        </View>
                        <View style={styles.sliderButtons}>
                          <Pressable
                            style={({ pressed }) => [styles.sliderButton, pressed && styles.pressed]}
                            onPress={() => adjustVolume('down')}>
                            <Ionicons name="remove" size={24} color="#f0f6fc" />
                          </Pressable>
                          <Pressable
                            style={({ pressed }) => [styles.sliderButton, pressed && styles.pressed]}
                            onPress={() => adjustVolume('up')}>
                            <Ionicons name="add" size={24} color="#f0f6fc" />
                          </Pressable>
                        </View>
                      </View>
                      <Ionicons name="volume-high" size={24} color="#8b949e" />
                    </View>
                    <Pressable
                      style={({ pressed }) => [styles.muteButtonFull, pressed && styles.pressed]}
                      onPress={toggleMute}>
                      <Ionicons 
                        name={isMuted ? "volume-mute" : "volume-high"} 
                        size={24} 
                        color="#ffffff" 
                      />
                      <Text style={styles.muteButtonText}>{isMuted ? 'Unmute' : 'Mute'}</Text>
                    </Pressable>
                  </View>
                </View>
              </ScrollView>
            )}

            {activeTab === 'apps' && (
              <ScrollView
                style={styles.remoteScroll}
                contentContainerStyle={styles.remoteScrollContent}
                showsVerticalScrollIndicator={false}>
                <View style={styles.appsContainer}>
                  <View style={styles.appsHeader}>
                    <Text style={styles.appsTitle}>Apps</Text>
                    <Pressable
                      style={({ pressed }) => [styles.refreshButton, pressed && styles.pressed]}
                      onPress={fetchApps}>
                      <Ionicons name="refresh" size={20} color="#58a6ff" />
                    </Pressable>
                  </View>
                  <Text style={styles.appsSubtitle}>Tap an app to launch it on LinuxTV</Text>
                  
                  {/* Add App Card */}
                  <View style={styles.addAppCard}>
                    <Text style={styles.addAppCardTitle}>Add New App</Text>
                    <View style={styles.addAppChoiceButtons}>
                      <Pressable
                        style={[
                          styles.addAppChoiceButton,
                          addAppMode === 'custom' && styles.addAppChoiceButtonActive,
                        ]}
                        onPress={showCustomApp}>
                        <Ionicons 
                          name="create-outline" 
                          size={20} 
                          color={addAppMode === 'custom' ? '#58a6ff' : '#8b949e'} 
                        />
                        <Text style={[
                          styles.addAppChoiceButtonText,
                          addAppMode === 'custom' && styles.addAppChoiceButtonTextActive,
                        ]}>
                          Custom
                        </Text>
                      </Pressable>
                      <Pressable
                        style={[
                          styles.addAppChoiceButton,
                          addAppMode === 'recommended' && styles.addAppChoiceButtonActive,
                        ]}
                        onPress={showRecommendedApps}>
                        <Ionicons 
                          name="star-outline" 
                          size={20} 
                          color={addAppMode === 'recommended' ? '#58a6ff' : '#8b949e'} 
                        />
                        <Text style={[
                          styles.addAppChoiceButtonText,
                          addAppMode === 'recommended' && styles.addAppChoiceButtonTextActive,
                        ]}>
                          Recommended
                        </Text>
                      </Pressable>
                    </View>
                    
                    {/* Custom App Form */}
                    {isAddAppVisible && addAppMode === 'custom' && (
                      <View style={styles.addAppForm}>
                        <TextInput
                          style={styles.appInput}
                          placeholder="App Name"
                          placeholderTextColor="#8b949e"
                          value={newAppName}
                          onChangeText={setNewAppName}
                        />
                        
                        <View style={styles.appTypeSelector}>
                          <Pressable
                            style={[styles.appTypeButton, newAppType === 'native' && styles.appTypeButtonActive]}
                            onPress={() => setNewAppType('native')}>
                            <Ionicons name="desktop" size={16} color={newAppType === 'native' ? '#58a6ff' : '#8b949e'} />
                            <Text style={[styles.appTypeText, newAppType === 'native' && styles.appTypeTextActive]}>
                              Native
                            </Text>
                          </Pressable>
                          <Pressable
                            style={[styles.appTypeButton, newAppType === 'web' && styles.appTypeButtonActive]}
                            onPress={() => setNewAppType('web')}>
                            <Ionicons name="globe" size={16} color={newAppType === 'web' ? '#58a6ff' : '#8b949e'} />
                            <Text style={[styles.appTypeText, newAppType === 'web' && styles.appTypeTextActive]}>
                              Web
                            </Text>
                          </Pressable>
                        </View>
                        
                        {newAppType === 'native' ? (
                          <TextInput
                            style={styles.appInput}
                            placeholder="Command (e.g., vlc, firefox)"
                            placeholderTextColor="#8b949e"
                            value={newAppCommand}
                            onChangeText={setNewAppCommand}
                          />
                        ) : (
                          <TextInput
                            style={styles.appInput}
                            placeholder="URL (e.g., https://youtube.com)"
                            placeholderTextColor="#8b949e"
                            value={newAppUrl}
                            onChangeText={setNewAppUrl}
                            keyboardType="url"
                            autoCapitalize="none"
                          />
                        )}
                        
                        <View style={styles.addAppButtons}>
                          <Pressable
                            style={[styles.addAppActionButton, styles.cancelButton]}
                            onPress={() => { setIsAddAppVisible(false); setAddAppMode(null); }}>
                            <Text style={styles.cancelButtonText}>Cancel</Text>
                          </Pressable>
                          <Pressable
                            style={[styles.addAppActionButton, styles.saveButton]}
                            onPress={addNewApp}>
                            <Text style={styles.saveButtonText}>Add App</Text>
                          </Pressable>
                        </View>
                      </View>
                    )}
                    
                    {/* Recommended Apps */}
                    {addAppMode === 'recommended' && (
                      <View style={styles.recommendedAppsContainer}>
                        {addAppsLoading ? (
                          <View style={styles.settingsLoading}>
                            <Ionicons name="sync" size={32} color="#58a6ff" />
                            <Text style={styles.settingsLoadingText}>Loading apps...</Text>
                          </View>
                        ) : (
                          <>
                            {/* Available to Add */}
                            {availableApps.filter(app => !serverApps.some(serverApp => serverApp.id === app.id)).length > 0 && (
                              <>
                                <Text style={styles.recommendedSectionTitle}>Available to Add</Text>
                                {availableApps
                                  .filter(app => !serverApps.some(serverApp => serverApp.id === app.id))
                                  .map((app) => (
                                    <Pressable
                                      key={app.id}
                                      style={styles.appItem}
                                      onPress={() => addAppToSystem(app.id, app.name, app.kind || 'native')}>
                                      <View style={styles.appItemLeft}>
                                        {app.icon ? (
                                          <RNImage 
                                            source={{ uri: app.icon }} 
                                            style={styles.appItemIcon}
                                            resizeMode="contain"
                                          />
                                        ) : (
                                          <Ionicons 
                                            name={app.kind === 'web' ? 'globe-outline' : 'desktop-outline'} 
                                            size={20} 
                                            color="#58a6ff" 
                                          />
                                        )}
                                        <View style={styles.appItemText}>
                                          <Text style={styles.appName}>{app.name}</Text>
                                          <Text style={styles.appCategory}>{app.category || (app.kind === 'web' ? 'Web App' : 'Native App')}</Text>
                                        </View>
                                      </View>
                                      <Ionicons name="add-circle-outline" size={20} color="#3fb950" />
                                    </Pressable>
                                  ))}
                              </>
                            )}
                            
                            {/* Already Added */}
                            {availableApps.filter(app => serverApps.some(serverApp => serverApp.id === app.id)).length > 0 && (
                              <>
                                <Text style={styles.recommendedSectionTitle}>Already Added</Text>
                                {availableApps
                                  .filter(app => serverApps.some(serverApp => serverApp.id === app.id))
                                  .map((app) => (
                                    <Pressable
                                      key={`added-${app.id}`}
                                      style={[styles.appItem, styles.appItemAdded]}>
                                      <View style={styles.appItemLeft}>
                                        {app.icon ? (
                                          <RNImage 
                                            source={{ uri: app.icon }} 
                                            style={styles.appItemIcon}
                                            resizeMode="contain"
                                          />
                                        ) : (
                                          <Ionicons 
                                            name={app.kind === 'web' ? 'globe-outline' : 'desktop-outline'} 
                                            size={20} 
                                            color="#3fb950" 
                                          />
                                        )}
                                        <View style={styles.appItemText}>
                                          <Text style={styles.appName}>{app.name}</Text>
                                          <Text style={styles.appCategory}>{app.category || (app.kind === 'web' ? 'Web App' : 'Native App')}</Text>
                                        </View>
                                      </View>
                                      <Pressable
                                        style={styles.appRemoveButton}
                                        onPress={() => {
                                          Alert.alert(
                                            'Remove App',
                                            `Remove ${app.name} from launcher?`,
                                            [
                                              { text: 'Cancel', style: 'cancel' },
                                              { 
                                                text: 'Remove', 
                                                style: 'destructive',
                                                onPress: () => {
                                                  setAddAppsLoading(true);
                                                  setAddAppsMessage(`Removing ${app.name}...`);
                                                  sendSettingsRequest('remove_app', { id: app.id });
                                                }
                                              },
                                            ]
                                          );
                                        }}>
                                        <Ionicons name="trash-outline" size={18} color="#f85149" />
                                      </Pressable>
                                    </Pressable>
                                  ))}
                              </>
                            )}
                            
                            {availableApps.length === 0 && !addAppsLoading && (
                              <View style={styles.settingsEmpty}>
                                <Ionicons name="grid-outline" size={48} color="#8b949e" />
                                <Text style={styles.settingsEmptyText}>No apps found</Text>
                              </View>
                            )}
                            
                            {availableApps.filter(app => !serverApps.some(serverApp => serverApp.id === app.id)).length === 0 && 
                             availableApps.filter(app => serverApps.some(serverApp => serverApp.id === app.id)).length > 0 && (
                              <View style={styles.settingsEmpty}>
                                <Ionicons name="checkmark-circle-outline" size={48} color="#3fb950" />
                                <Text style={styles.settingsEmptyText}>All apps are already added</Text>
                              </View>
                            )}
                            
                            {addAppsMessage ? (
                              <View style={[
                                styles.settingsMessage,
                                addAppsMessage.includes('added') && styles.settingsMessageSuccess,
                                addAppsMessage.includes('already') && styles.settingsMessageSuccess,
                                addAppsMessage.includes('removed') && styles.settingsMessageSuccess,
                                (addAppsMessage.includes('Could not') || addAppsMessage.includes('Error')) && styles.settingsMessageError,
                              ]}>
                                <Text style={styles.settingsMessageText}>{addAppsMessage}</Text>
                              </View>
                            ) : null}
                          </>
                        )}
                      </View>
                    )}
                  </View>
                  
                  <View style={styles.appsGrid}>
                    {/* Native Apps Section */}
                    {serverApps.filter(app => app.kind === 'native').length > 0 && (
                      <>
                        <View style={styles.sectionHeader}>
                          <Ionicons name="desktop" size={18} color="#58a6ff" />
                          <Text style={styles.sectionTitle}>Native Apps</Text>
                        </View>
                        {serverApps
                          .filter(app => app.kind === 'native')
                          .map((app) => (
                            <Pressable
                              key={app.id}
                              style={({ pressed }) => [styles.appCard, pressed && styles.pressed]}>
                              <Pressable
                                style={({ pressed }) => [styles.deleteButton, pressed && styles.pressed]}
                                onPress={() => removeApp(app.id, app.name)}>
                                <Ionicons name="trash" size={16} color="#f85149" />
                              </Pressable>
                              <Pressable
                                style={styles.appCardContent}
                                onPress={() => launchApp(app.id)}>
                                <View style={styles.appIconContainer}>
                                  {app.icon ? (
                                    <RNImage 
                                      source={{ uri: app.icon }} 
                                      style={styles.appIconImage}
                                      resizeMode="contain"
                                    />
                                  ) : (
                                    <View style={styles.appIconCircle}>
                                      <Ionicons 
                                        name="desktop" 
                                        size={28} 
                                        color="#58a6ff" 
                                      />
                                    </View>
                                  )}
                                </View>
                                <Text style={styles.appName}>{app.name}</Text>
                              </Pressable>
                            </Pressable>
                          ))}
                      </>
                    )}
                    
                    {/* Web Apps Section */}
                    {serverApps.filter(app => app.kind === 'web').length > 0 && (
                      <>
                        <View style={styles.sectionHeader}>
                          <Ionicons name="globe" size={18} color="#58a6ff" />
                          <Text style={styles.sectionTitle}>Web Apps</Text>
                        </View>
                        {serverApps
                          .filter(app => app.kind === 'web')
                          .map((app) => (
                            <Pressable
                              key={app.id}
                              style={({ pressed }) => [styles.appCard, pressed && styles.pressed]}>
                              <Pressable
                                style={({ pressed }) => [styles.deleteButton, pressed && styles.pressed]}
                                onPress={() => removeApp(app.id, app.name)}>
                                <Ionicons name="trash" size={16} color="#f85149" />
                              </Pressable>
                              <Pressable
                                style={styles.appCardContent}
                                onPress={() => launchApp(app.id)}>
                                <View style={styles.appIconContainer}>
                                  {app.icon ? (
                                    <RNImage 
                                      source={{ uri: app.icon }} 
                                      style={styles.appIconImage}
                                      resizeMode="contain"
                                    />
                                  ) : (
                                    <View style={styles.appIconCircle}>
                                      <Ionicons 
                                        name="globe" 
                                        size={28} 
                                        color="#58a6ff" 
                                      />
                                    </View>
                                  )}
                                </View>
                                <Text style={styles.appName}>{app.name}</Text>
                              </Pressable>
                            </Pressable>
                          ))}
                      </>
                    )}
                  </View>
                  
                  {serverApps.length === 0 && (
                    <View style={styles.emptyApps}>
                      <Ionicons name="apps" size={64} color="#8b949e" />
                      <Text style={styles.emptyAppsText}>No apps found</Text>
                      <Text style={styles.emptyAppsSubtext}>Tap refresh to load apps from server</Text>
                    </View>
                  )}
                </View>
              </ScrollView>
            )}

            {activeTab === 'kodi' && (
              <ScrollView
                style={styles.remoteScroll}
                contentContainerStyle={styles.remoteScrollContent}
                showsVerticalScrollIndicator={false}>
                <View style={styles.kodiContainer}>
                  <View style={styles.kodiHeader}>
                    <View style={styles.kodiHeaderTitleWrap}>
                      {selectedKodiGroup ? (
                        <Pressable
                          style={({ pressed }) => [styles.kodiBackButton, pressed && styles.pressed]}
                          onPress={() => {
                            setSelectedKodiGroup(null);
                            setKodiChannels([]);
                            setKodiError(null);
                            setKodiSearchQuery('');
                          }}>
                          <Ionicons name="chevron-back" size={18} color="#58a6ff" />
                          <Text style={styles.kodiBackButtonText}>Folders</Text>
                        </Pressable>
                      ) : null}
                      <Text style={styles.kodiTitle}>
                        {selectedKodiGroup ? selectedKodiGroup.label : 'Kodi Folders'}
                      </Text>
                    </View>
                    <Pressable
                      style={({ pressed }) => [styles.refreshButton, pressed && styles.pressed]}
                      onPress={() => {
                        void (selectedKodiGroup ? fetchKodiChannels() : fetchKodiGroups());
                      }}>
                      <Ionicons name="refresh" size={20} color="#58a6ff" />
                    </Pressable>
                  </View>
                  <Text style={styles.kodiSubtitle}>
                    {selectedKodiGroup
                      ? 'Choose a channel to start playback'
                      : 'Open a channel folder, then pick the channel inside'}
                  </Text>
                  <View style={styles.kodiSearchWrap}>
                    <Ionicons name="search" size={18} color="#8b949e" />
                    <TextInput
                      value={kodiSearchQuery}
                      onChangeText={setKodiSearchQuery}
                      placeholder={selectedKodiGroup ? 'Search channels' : 'Search folders'}
                      placeholderTextColor="#8b949e"
                      autoCapitalize="none"
                      autoCorrect={false}
                      style={styles.kodiSearchInput}
                    />
                    {kodiSearchQuery ? (
                      <Pressable
                        style={({ pressed }) => [styles.kodiSearchClearButton, pressed && styles.pressed]}
                        onPress={() => setKodiSearchQuery('')}>
                        <Ionicons name="close-circle" size={18} color="#8b949e" />
                      </Pressable>
                    ) : null}
                  </View>
                  
                  {isKodiLoading && (
                    <View style={styles.kodiLoading}>
                      <Ionicons name="sync" size={48} color="#58a6ff" />
                      <Text style={styles.kodiLoadingText}>Loading channels...</Text>
                    </View>
                  )}
                  
                  {kodiError && !isKodiLoading && (
                    <View style={styles.kodiErrorContainer}>
                      <Ionicons name="alert-circle" size={48} color="#f85149" />
                      <Text style={styles.kodiErrorText}>{kodiError}</Text>
                      <Pressable
                        style={styles.kodiRetryButton}
                        onPress={() => {
                          void (selectedKodiGroup ? fetchKodiChannels() : fetchKodiGroups());
                        }}>
                        <Text style={styles.kodiRetryButtonText}>Retry</Text>
                      </Pressable>
                    </View>
                  )}
                  
                  {!isKodiLoading && !kodiError && !selectedKodiGroup && filteredKodiGroups.length > 0 && (
                    <View style={styles.channelsGrid}>
                      {filteredKodiGroups.map((group) => (
                        <Pressable
                          key={String(group.channelgroupid)}
                          style={({ pressed }) => [styles.channelCard, pressed && styles.pressed]}
                          onPress={() => {
                            setSelectedKodiGroup(group);
                            void fetchKodiChannels(undefined, group);
                          }}>
                          <View style={styles.channelIconContainer}>
                            <Ionicons name="folder-open" size={32} color="#58a6ff" />
                          </View>
                          <View style={styles.channelInfo}>
                            <Text style={styles.channelName}>{group.label}</Text>
                            <Text style={styles.channelMeta}>Kodi channel folder</Text>
                          </View>
                          <Ionicons name="chevron-forward" size={24} color="#8b949e" />
                        </Pressable>
                      ))}
                    </View>
                  )}

                  {!isKodiLoading && !kodiError && selectedKodiGroup && filteredKodiChannels.length > 0 && (
                    <View style={styles.channelsGrid}>
                      {filteredKodiChannels.map((channel) => (
                        <Pressable
                          key={channel.channelid}
                          style={({ pressed }) => [styles.channelCard, pressed && styles.pressed]}
                          onPress={() => playKodiChannel(channel.channelid, channel.label)}>
                          <View style={styles.channelIconContainer}>
                            {channel.thumbnail ? (
                              <>
                                {kodiChannelThumbnails[channel.channelid] ? (
                                  <RNImage 
                                    source={{ 
                                      uri: kodiChannelThumbnails[channel.channelid],
                                    }} 
                                    style={styles.channelThumbnailImage}
                                    resizeMode="cover"
                                  />
                                ) : (
                                  <Ionicons name="image" size={32} color="#8b949e" />
                                )}
                              </>
                            ) : (
                              <Ionicons name="tv" size={32} color="#58a6ff" />
                            )}
                          </View>
                          <View style={styles.channelInfo}>
                            <Text style={styles.channelNumber}>{channel.channelnumber}</Text>
                            <Text style={styles.channelName}>{channel.label}</Text>
                          </View>
                          <Ionicons name="play-circle" size={24} color="#238636" />
                        </Pressable>
                      ))}
                    </View>
                  )}
                  
                  {!isKodiLoading &&
                    !kodiError &&
                    !selectedKodiGroup &&
                    filteredKodiGroups.length === 0 && (
                    <View style={styles.emptyKodi}>
                      <Ionicons name="folder-open" size={64} color="#8b949e" />
                      <Text style={styles.emptyKodiText}>
                        {kodiSearchQuery ? 'No matching folders' : 'No folders found'}
                      </Text>
                      <Text style={styles.emptyKodiSubtext}>
                        {kodiSearchQuery
                          ? 'Try a different search term'
                          : 'Make sure Kodi is running and PVR channel groups are available'}
                      </Text>
                    </View>
                  )}

                  {!isKodiLoading &&
                    !kodiError &&
                    selectedKodiGroup &&
                    filteredKodiChannels.length === 0 && (
                    <View style={styles.emptyKodi}>
                      <Ionicons name="tv" size={64} color="#8b949e" />
                      <Text style={styles.emptyKodiText}>
                        {kodiSearchQuery ? 'No matching channels' : 'No channels in this folder'}
                      </Text>
                      <Text style={styles.emptyKodiSubtext}>
                        {kodiSearchQuery
                          ? 'Try a different search term'
                          : 'Try another Kodi folder or refresh this one'}
                      </Text>
                    </View>
                  )}
                </View>
              </ScrollView>
            )}

            {activeTab === 'keyboard' && (
              <View style={styles.keyboardContainer}>
                <View style={styles.keyboardInputWrapper}>
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
                    style={[styles.actionButton, styles.primaryButton, styles.sendButton]}
                    onPress={() => {
                      sendKeyboardText();
                      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                    }}>
                    <Ionicons name="paper-plane" size={20} color="#ffffff" />
                    <Text style={styles.primaryButtonText}>Send</Text>
                  </Pressable>
                </View>
                <View style={styles.keyboardSection}>
                  <Text style={styles.groupLabel}>Quick Keys</Text>
                  <View style={styles.specialKeysRow}>
                    <ControlButton
                      icon="checkmark-circle"
                      label="Enter"
                      onPress={() => {
                        sendSpecialKey('ENTER');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.keyButton}
                      textStyle={styles.keyButtonText}
                    />
                    <ControlButton
                      icon="ellipse-outline"
                      label="Space"
                      onPress={() => {
                        sendSpecialKey('SPACE');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.keyButton}
                      textStyle={styles.keyButtonText}
                    />
                    <ControlButton
                      icon="backspace-outline"
                      label="Backspace"
                      onPress={() => {
                        sendSpecialKey('BACKSPACE');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.keyButton}
                      textStyle={styles.keyButtonText}
                    />
                  </View>
                  <View style={styles.specialKeysRow}>
                    <ControlButton
                      icon="close-circle"
                      label="Esc"
                      onPress={() => {
                        sendSpecialKey('ESCAPE');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.keyButton}
                      textStyle={styles.keyButtonText}
                    />
                    <ControlButton
                      icon="arrow-forward"
                      label="Tab"
                      onPress={() => {
                        sendSpecialKey('TAB');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.keyButton}
                      textStyle={styles.keyButtonText}
                    />
                    <ControlButton
                      icon="arrow-back"
                      label="Shift+Tab"
                      onPress={() => {
                        sendAction('SHIFT_TAB');
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      }}
                      style={styles.keyButton}
                      textStyle={styles.keyButtonText}
                    />
                  </View>
                </View>
              </View>
            )}

            {activeTab === 'touchpad' && (
              <View style={styles.touchpadContainer}>
                <View style={styles.touchpadSurface} {...touchpadResponder.panHandlers}>
                  <View style={styles.touchpadInner}>
                    <Ionicons name="hand-left" size={48} color="#58a6ff" />
                    <Text style={styles.touchpadText}>Touchpad</Text>
                    <Text style={styles.touchpadHint}>Tap to click • Drag to move</Text>
                  </View>
                </View>
                <View style={styles.touchpadButtons}>
                  <ControlButton
                    label="Click"
                    onPress={() => {
                      sendPointerEvent('click');
                      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                    }}
                    style={styles.touchpadButton}
                    textStyle={styles.touchpadButtonText}
                  />
                  <ControlButton
                    label="Right Click"
                    onPress={() => {
                      sendPointerEvent('right_click');
                      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                    }}
                    style={styles.touchpadButton}
                    textStyle={styles.touchpadButtonText}
                  />
                </View>
              </View>
            )}
          </View>
        )}
      </View>

      {!showLoginScreen && (
        <View style={styles.tabBarContainer}>
          <View style={styles.tabBar}>
            {tabItems.map((tab) => (
              <Pressable
                key={tab.key}
                style={({ pressed }) => [
                  styles.tabItem,
                  activeTab === tab.key && styles.tabItemActive,
                  pressed && styles.pressed,
                ]}
                onPress={() => {
                  setActiveTab(tab.key);
                  Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                }}>
                <Ionicons
                  name={tab.icon}
                  size={22}
                  color={activeTab === tab.key ? '#238636' : '#8b949e'}
                />
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
        </View>
      )}

      <Modal
        transparent
        animationType="fade"
        visible={isMenuVisible}
        onRequestClose={() => setIsMenuVisible(false)}>
        <Pressable style={styles.menuOverlay} onPress={() => setIsMenuVisible(false)}>
          <Pressable style={styles.menuSheet} onPress={() => undefined}>
            {/* Header */}
            <View style={styles.menuHeader}>
              <Ionicons name="settings" size={24} color="#58a6ff" />
              <Text style={styles.menuHeaderTitle}>Settings</Text>
            </View>
            
            <View style={styles.menuDivider} />
            
            {!repositoryState.isDemoMode ? (
              <>
                {/* Systems Section */}
                <View style={styles.menuSection}>
                  <Text style={styles.menuSectionTitle}>Systems</Text>
                  {savedSystems.map((system) => (
                    <Pressable
                      key={system.id}
                      style={({ pressed }) => [
                        styles.systemRow,
                        system.id === activeSystemId && styles.systemRowActive,
                        pressed && styles.menuItemPressed,
                      ]}
                      onPress={() => {
                        void switchToSystem(system);
                      }}>
                      <View style={styles.systemRowLeft}>
                        <Ionicons 
                          name={system.id === activeSystemId ? "radio-button-on" : "radio-button-off"} 
                          size={18} 
                          color={system.id === activeSystemId ? "#3fb950" : "#8b949e"} 
                        />
                        <View style={styles.systemRowText}>
                          <Text style={styles.systemName}>{system.name}</Text>
                          <Text style={styles.systemMeta}>
                            {system.ipAddress}:{system.port}
                          </Text>
                        </View>
                      </View>
                      {system.id === activeSystemId && (
                        <View style={styles.activeBadge}>
                          <Text style={styles.activeBadgeText}>Active</Text>
                        </View>
                      )}
                    </Pressable>
                  ))}
                </View>

                <View style={styles.menuDivider} />
                
                {/* System Actions */}
                <Pressable
                  style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
                  onPress={openAddSystemEditor}>
                  <View style={styles.menuItemContent}>
                    <Ionicons name="add-circle" size={20} color="#58a6ff" />
                    <Text style={styles.menuItemText}>Add System</Text>
                  </View>
                </Pressable>
                
                {activeSystem && (
                  <Pressable
                    style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
                    onPress={openEditSystemEditor}>
                    <View style={styles.menuItemContent}>
                      <Ionicons name="create" size={20} color="#58a6ff" />
                      <Text style={styles.menuItemText}>Edit System</Text>
                    </View>
                  </Pressable>
                )}
                
                {activeSystem && (
                  <Pressable
                    style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
                    onPress={confirmRemoveActiveSystem}>
                    <View style={styles.menuItemContent}>
                      <Ionicons name="trash" size={20} color="#f85149" />
                      <Text style={styles.menuItemDangerText}>Remove System</Text>
                    </View>
                  </Pressable>
                )}
                
                <View style={styles.menuDivider} />
              </>
            ) : null}

            {/* Device Settings */}
            <Pressable
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
              onPress={() => {
                setIsMenuVisible(false);
                setIsWifiVisible(true);
                fetchWifiNetworks();
              }}>
              <View style={styles.menuItemContent}>
                <Ionicons name="wifi" size={20} color="#58a6ff" />
                <Text style={styles.menuItemText}>Wi-Fi</Text>
              </View>
            </Pressable>
            
            <Pressable
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
              onPress={() => {
                setIsMenuVisible(false);
                setIsBluetoothVisible(true);
                fetchBluetoothDevices();
              }}>
              <View style={styles.menuItemContent}>
                <Ionicons name="bluetooth" size={20} color="#58a6ff" />
                <Text style={styles.menuItemText}>Bluetooth</Text>
              </View>
            </Pressable>
            
            <Pressable
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
              onPress={() => {
                setIsMenuVisible(false);
                setIsSoundVisible(true);
                fetchSoundDevices();
              }}>
              <View style={styles.menuItemContent}>
                <Ionicons name="volume-high" size={20} color="#58a6ff" />
                <Text style={styles.menuItemText}>Sound</Text>
              </View>
            </Pressable>
            
            <View style={styles.menuDivider} />

            {/* Power Actions */}
            <Pressable
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
              onPress={() => confirmPowerAction('SHUTDOWN')}>
              <View style={styles.menuItemContent}>
                <Ionicons name="power" size={20} color="#f85149" />
                <Text style={styles.menuItemDangerText}>Shutdown</Text>
              </View>
            </Pressable>
            
            <Pressable
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
              onPress={() => confirmPowerAction('REBOOT')}>
              <View style={styles.menuItemContent}>
                <Ionicons name="refresh" size={20} color="#f85149" />
                <Text style={styles.menuItemDangerText}>Reboot</Text>
              </View>
            </Pressable>
            
            <Pressable
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
              onPress={() => confirmPowerAction('SLEEP')}>
              <View style={styles.menuItemContent}>
                <Ionicons name="moon" size={20} color="#ffa657" />
                <Text style={styles.menuItemWarningText}>Sleep</Text>
              </View>
            </Pressable>
            
            <View style={styles.menuDivider} />
            
            <Pressable
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
              onPress={confirmLogout}>
              <View style={styles.menuItemContent}>
                <Ionicons name="log-out" size={20} color="#f85149" />
                <Text style={styles.menuItemDangerText}>
                  {repositoryState.isDemoMode ? 'Exit Demo' : 'Remove All Systems'}
                </Text>
              </View>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>

      <Modal
        transparent
        animationType="slide"
        visible={isSystemEditorVisible}
        onRequestClose={() => setIsSystemEditorVisible(false)}>
        <Pressable
          style={styles.editorOverlay}
          onPress={() => {
            setIsSystemEditorVisible(false);
            resetEditorToActiveSystem();
          }}>
          <Pressable style={styles.editorSheet} onPress={() => undefined}>
            <Text style={styles.editorTitle}>
              {editingSystemId ? 'Edit system' : 'Add system'}
            </Text>
            <Text style={styles.editorSubtitle}>
              Save another LinuxTV target and switch to it from the gear anytime.
            </Text>
            <TextInput
              value={systemName}
              onChangeText={setSystemName}
              placeholder="System name"
              placeholderTextColor="#8b949e"
              autoCapitalize="words"
              autoCorrect={false}
              style={styles.input}
            />
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
            <Text style={styles.formSectionLabel}>Kodi web server login</Text>
            <View style={styles.addressRow}>
              <TextInput
                value={kodiPort}
                onChangeText={setKodiPort}
                placeholder="Kodi port"
                placeholderTextColor="#8b949e"
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="number-pad"
                style={[styles.input, styles.portInput]}
              />
            </View>
            <TextInput
              value={kodiUsername}
              onChangeText={setKodiUsername}
              placeholder="Kodi username"
              placeholderTextColor="#8b949e"
              autoCapitalize="none"
              autoCorrect={false}
              style={styles.input}
            />
            <TextInput
              value={kodiPassword}
              onChangeText={setKodiPassword}
              placeholder="Kodi password"
              placeholderTextColor="#8b949e"
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              style={styles.input}
            />
            <Pressable
              style={[styles.actionButton, styles.primaryButton]}
              onPress={saveSystemAndConnect}>
              <Text style={styles.primaryButtonText}>
                {editingSystemId ? 'Save & Switch' : 'Add & Switch'}
              </Text>
            </Pressable>
            <Pressable
              style={[styles.actionButton, styles.ghostButton]}
              onPress={() => {
                setIsSystemEditorVisible(false);
                resetEditorToActiveSystem();
              }}>
              <Text style={styles.ghostButtonText}>Cancel</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>

      <Modal
        transparent
        animationType="slide"
        visible={isKodiAuthVisible}
        onRequestClose={() => setIsKodiAuthVisible(false)}>
        <Pressable
          style={styles.editorOverlay}
          onPress={() => setIsKodiAuthVisible(false)}>
          <Pressable style={styles.editorSheet} onPress={() => undefined}>
            <Text style={styles.editorTitle}>Kodi Login</Text>
            <Text style={styles.editorSubtitle}>
              Kodi is reachable, but it needs its web server username and password.
            </Text>
            <TextInput
              value={kodiAuthPort}
              onChangeText={setKodiAuthPort}
              placeholder="Kodi port"
              placeholderTextColor="#8b949e"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="number-pad"
              style={[styles.input, styles.portInput]}
            />
            <TextInput
              value={kodiAuthUsername}
              onChangeText={setKodiAuthUsername}
              placeholder="Kodi username"
              placeholderTextColor="#8b949e"
              autoCapitalize="none"
              autoCorrect={false}
              style={styles.input}
            />
            <TextInput
              value={kodiAuthPassword}
              onChangeText={setKodiAuthPassword}
              placeholder="Kodi password"
              placeholderTextColor="#8b949e"
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              style={styles.input}
            />
            <Pressable
              style={[styles.actionButton, styles.primaryButton]}
              onPress={() => {
                void saveKodiAuthForActiveSystem().then((updatedSystem) => {
                  if (!updatedSystem) {
                    return;
                  }
                  void (selectedKodiGroup
                    ? fetchKodiChannels(updatedSystem, selectedKodiGroup)
                    : fetchKodiGroups(updatedSystem));
                });
              }}>
              <Text style={styles.primaryButtonText}>Save & Retry</Text>
            </Pressable>
            <Pressable
              style={[styles.actionButton, styles.ghostButton]}
              onPress={() => setIsKodiAuthVisible(false)}>
              <Text style={styles.ghostButtonText}>Cancel</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>

      {/* WiFi Settings Modal */}
      <Modal
        transparent
        animationType="slide"
        visible={isWifiVisible}
        onRequestClose={() => setIsWifiVisible(false)}>
        <Pressable style={styles.settingsOverlay} onPress={() => setIsWifiVisible(false)}>
          <Pressable style={styles.settingsSheet} onPress={() => undefined}>
            <View style={styles.settingsHeader}>
              <Ionicons name="wifi" size={24} color="#58a6ff" />
              <Text style={styles.settingsTitle}>Wi-Fi Settings</Text>
              <Pressable onPress={() => setIsWifiVisible(false)} style={styles.settingsCloseButton}>
                <Ionicons name="close" size={24} color="#8b949e" />
              </Pressable>
            </View>
            
            <ScrollView style={styles.settingsContent}>
              <Text style={styles.settingsSectionTitle}>Available Networks</Text>
              
              {wifiLoading ? (
                <View style={styles.settingsLoading}>
                  <Ionicons name="sync" size={32} color="#58a6ff" />
                  <Text style={styles.settingsLoadingText}>Scanning networks...</Text>
                </View>
              ) : (
                <>
                  {wifiNetworks.map((network) => (
                    <Pressable
                      key={network.ssid}
                      style={[
                        styles.networkItem,
                        currentWifi === network.ssid && styles.networkItemActive,
                        selectedWifiNetwork?.ssid === network.ssid && styles.networkItemActive,
                      ]}
                      onPress={() => {
                        if (currentWifi === network.ssid) {
                          setWifiMessage(`Already connected to ${network.ssid}`);
                        } else {
                          selectWifiNetwork(network.ssid, network.security || '');
                        }
                      }}>
                      <View style={styles.networkItemLeft}>
                        <Ionicons 
                          name={currentWifi === network.ssid ? "checkmark-circle" : "wifi"} 
                          size={20} 
                          color={currentWifi === network.ssid ? "#3fb950" : "#8b949e"} 
                        />
                        <View style={styles.networkItemText}>
                          <Text style={styles.networkName}>{network.label || network.ssid}</Text>
                          {network.security && network.security.toLowerCase() !== 'open' && (
                            <Ionicons name="lock-closed" size={12} color="#8b949e" />
                          )}
                        </View>
                      </View>
                      {network.signal && (
                        <Text style={styles.networkSignal}>{network.signal}%</Text>
                      )}
                    </Pressable>
                  ))}
                  
                  {wifiNetworks.length === 0 && (
                    <View style={styles.settingsEmpty}>
                      <Ionicons name="wifi-outline" size={48} color="#8b949e" />
                      <Text style={styles.settingsEmptyText}>No networks found</Text>
                    </View>
                  )}
                </>
              )}
              
              {selectedWifiNetwork && selectedWifiNetwork.security && selectedWifiNetwork.security.toLowerCase() !== 'open' && (
                <View style={styles.settingsSection}>
                  <Text style={styles.settingsSectionTitle}>Password for {selectedWifiNetwork.ssid}</Text>
                  <TextInput
                    value={wifiPassword}
                    onChangeText={setWifiPassword}
                    placeholder="Enter Wi-Fi password"
                    placeholderTextColor="#8b949e"
                    secureTextEntry
                    style={styles.settingsInput}
                  />
                  <Pressable
                    style={styles.settingsActionButton}
                    onPress={connectToSelectedWifi}>
                    <Ionicons name="checkmark" size={20} color="#3fb950" />
                    <Text style={styles.settingsActionButtonText}>Connect</Text>
                  </Pressable>
                </View>
              )}
              
              {wifiMessage ? (
                <View style={[
                  styles.settingsMessage,
                  wifiMessage.includes('Connected') && styles.settingsMessageSuccess,
                  wifiMessage.includes('Could not') && styles.settingsMessageError,
                ]}>
                  <Text style={styles.settingsMessageText}>{wifiMessage}</Text>
                </View>
              ) : null}
              
              <Pressable
                style={styles.settingsActionButton}
                onPress={fetchWifiNetworks}>
                <Ionicons name="refresh" size={20} color="#58a6ff" />
                <Text style={styles.settingsActionButtonText}>Refresh Networks</Text>
              </Pressable>
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>

      {/* Bluetooth Settings Modal */}
      <Modal
        transparent
        animationType="slide"
        visible={isBluetoothVisible}
        onRequestClose={() => setIsBluetoothVisible(false)}>
        <Pressable style={styles.settingsOverlay} onPress={() => setIsBluetoothVisible(false)}>
          <Pressable style={styles.settingsSheet} onPress={() => undefined}>
            <View style={styles.settingsHeader}>
              <Ionicons name="bluetooth" size={24} color="#58a6ff" />
              <Text style={styles.settingsTitle}>Bluetooth Settings</Text>
              <Pressable onPress={() => setIsBluetoothVisible(false)} style={styles.settingsCloseButton}>
                <Ionicons name="close" size={24} color="#8b949e" />
              </Pressable>
            </View>
            
            <ScrollView style={styles.settingsContent}>
              <Text style={styles.settingsSectionTitle}>Devices</Text>
              
              {bluetoothLoading ? (
                <View style={styles.settingsLoading}>
                  <Ionicons name="sync" size={32} color="#58a6ff" />
                  <Text style={styles.settingsLoadingText}>Scanning devices...</Text>
                </View>
              ) : (
                <>
                  {bluetoothDevices.map((device) => (
                    <View key={device.mac} style={styles.bluetoothItem}>
                      <View style={styles.bluetoothItemLeft}>
                        <Ionicons 
                          name={device.connected ? "bluetooth" : "bluetooth-outline"} 
                          size={20} 
                          color={device.connected ? "#3fb950" : "#8b949e"} 
                        />
                        <View style={styles.bluetoothItemText}>
                          <Text style={styles.bluetoothName}>{device.name || device.label}</Text>
                          <Text style={styles.bluetoothMac}>{device.mac}</Text>
                        </View>
                      </View>
                      <View style={styles.bluetoothActions}>
                        {!device.connected && (
                          <Pressable
                            style={styles.bluetoothConnectButton}
                            onPress={() => connectToBluetooth(device.mac)}>
                            <Text style={styles.bluetoothConnectText}>Connect</Text>
                          </Pressable>
                        )}
                        {device.connected && (
                          <Text style={styles.bluetoothConnectedText}>Connected</Text>
                        )}
                        <Pressable
                          style={styles.bluetoothRemoveButton}
                          onPress={() => {
                            Alert.alert(
                              'Remove Device',
                              `Remove ${device.name}?`,
                              [
                                { text: 'Cancel', style: 'cancel' },
                                { text: 'Remove', style: 'destructive', onPress: () => removeBluetoothDevice(device.mac) },
                              ]
                            );
                          }}>
                          <Ionicons name="trash-outline" size={18} color="#f85149" />
                        </Pressable>
                      </View>
                    </View>
                  ))}
                  
                  {bluetoothDevices.length === 0 && (
                    <View style={styles.settingsEmpty}>
                      <Ionicons name="bluetooth-outline" size={48} color="#8b949e" />
                      <Text style={styles.settingsEmptyText}>No devices found</Text>
                    </View>
                  )}
                </>
              )}
              
              {bluetoothMessage ? (
                <View style={[
                  styles.settingsMessage,
                  bluetoothMessage.includes('Connected') && styles.settingsMessageSuccess,
                  bluetoothMessage.includes('Could not') && styles.settingsMessageError,
                ]}>
                  <Text style={styles.settingsMessageText}>{bluetoothMessage}</Text>
                </View>
              ) : null}
              
              <Pressable
                style={styles.settingsActionButton}
                onPress={fetchBluetoothDevices}>
                <Ionicons name="refresh" size={20} color="#58a6ff" />
                <Text style={styles.settingsActionButtonText}>Refresh Devices</Text>
              </Pressable>
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>

      {/* Sound Settings Modal */}
      <Modal
        transparent
        animationType="slide"
        visible={isSoundVisible}
        onRequestClose={() => setIsSoundVisible(false)}>
        <Pressable style={styles.settingsOverlay} onPress={() => setIsSoundVisible(false)}>
          <Pressable style={styles.settingsSheet} onPress={() => undefined}>
            <View style={styles.settingsHeader}>
              <Ionicons name="volume-high" size={24} color="#58a6ff" />
              <Text style={styles.settingsTitle}>Sound Settings</Text>
              <Pressable onPress={() => setIsSoundVisible(false)} style={styles.settingsCloseButton}>
                <Ionicons name="close" size={24} color="#8b949e" />
              </Pressable>
            </View>
            
            <ScrollView style={styles.settingsContent}>
              <Text style={styles.settingsSectionTitle}>Audio Output Devices</Text>
              
              {soundLoading ? (
                <View style={styles.settingsLoading}>
                  <Ionicons name="sync" size={32} color="#58a6ff" />
                  <Text style={styles.settingsLoadingText}>Loading devices...</Text>
                </View>
              ) : (
                <>
                  {soundSpeakers.map((speaker) => (
                    <Pressable
                      key={speaker.name}
                      style={[
                        styles.speakerItem,
                        defaultSink === speaker.name && styles.speakerItemActive,
                      ]}
                      onPress={() => {
                        if (defaultSink !== speaker.name) {
                          setSoundDevice(speaker.name);
                        }
                      }}>
                      <View style={styles.speakerItemLeft}>
                        <Ionicons 
                          name={defaultSink === speaker.name ? "volume-high" : "volume-low"} 
                          size={20} 
                          color={defaultSink === speaker.name ? "#3fb950" : "#8b949e"} 
                        />
                        <Text style={styles.speakerName}>{speaker.label}</Text>
                      </View>
                      {defaultSink === speaker.name && (
                        <View style={styles.speakerActiveBadge}>
                          <Text style={styles.speakerActiveText}>Default</Text>
                        </View>
                      )}
                    </Pressable>
                  ))}
                  
                  {soundSpeakers.length === 0 && (
                    <View style={styles.settingsEmpty}>
                      <Ionicons name="volume-mute-outline" size={48} color="#8b949e" />
                      <Text style={styles.settingsEmptyText}>No audio devices found</Text>
                    </View>
                  )}
                </>
              )}
              
              {soundMessage ? (
                <View style={[
                  styles.settingsMessage,
                  soundMessage.includes('updated') && styles.settingsMessageSuccess,
                  soundMessage.includes('Failed') && styles.settingsMessageError,
                ]}>
                  <Text style={styles.settingsMessageText}>{soundMessage}</Text>
                </View>
              ) : null}
              
              <Pressable
                style={styles.settingsActionButton}
                onPress={fetchSoundDevices}>
                <Ionicons name="refresh" size={20} color="#58a6ff" />
                <Text style={styles.settingsActionButtonText}>Refresh Devices</Text>
              </Pressable>
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

function ControlButton({
  label,
  icon,
  onPress,
  onPressIn,
  onPressOut,
  style,
  textStyle,
  iconSize = 20,
}: {
  label: string;
  icon?: ComponentProps<typeof Ionicons>['name'];
  onPress: () => void;
  onPressIn?: () => void;
  onPressOut?: () => void;
  style?: StyleProp<ViewStyle>;
  textStyle?: StyleProp<TextStyle>;
  iconSize?: number;
}) {
  return (
    <Pressable
      style={({ pressed }) => [style, pressed && styles.pressed]}
      onPress={onPress}
      onPressIn={onPressIn}
      onPressOut={onPressOut}>
      {icon && <Ionicons name={icon} size={iconSize} color="#c9d1d9" style={styles.buttonIcon} />}
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
    paddingHorizontal: 12,
    paddingTop: 16,
    paddingBottom: 0,
    backgroundColor: '#0a0e17',
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
    marginBottom: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#21262d',
    gap: 16,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    flex: 1,
  },
  headerTextWrap: {
    flex: 1,
  },
  headerMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 2,
  },
  title: {
    color: '#f0f6fc',
    fontSize: 32,
    fontWeight: '800',
    letterSpacing: -0.5,
  },
  deviceName: {
    color: '#8b949e',
    fontSize: 13,
    flexShrink: 0,
  },
  headerStatusText: {
    color: '#58a6ff',
    fontSize: 12,
    flex: 1,
  },
  statusDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: '#0a0e17',
  },
  statusOnline: {
    backgroundColor: '#238636',
    shadowColor: '#238636',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.8,
    shadowRadius: 4,
  },
  statusOffline: {
    backgroundColor: '#da3633',
    shadowColor: '#da3633',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.8,
    shadowRadius: 4,
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
  loginHeader: {
    alignItems: 'center',
    gap: 12,
    marginBottom: 8,
  },
  helperText: {
    color: '#f0f6fc',
    fontSize: 20,
    fontWeight: '700',
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
    gap: 20,
    paddingBottom: 24,
    paddingTop: 8,
  },
  remoteControl: {
    gap: 18,
  },
  appsContainer: {
    gap: 16,
  },
  appsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  appsHeaderButtons: {
    flexDirection: 'row',
    gap: 8,
  },
  appsTitle: {
    color: '#f0f6fc',
    fontSize: 24,
    fontWeight: '800',
  },
  refreshButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
  },
  appsSubtitle: {
    color: '#8b949e',
    fontSize: 13,
    marginBottom: 8,
  },
  appsGrid: {
    gap: 12,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 8,
    marginBottom: 4,
    paddingHorizontal: 4,
  },
  sectionTitle: {
    color: '#58a6ff',
    fontSize: 16,
    fontWeight: '700',
  },
  appCard: {
    width: '100%',
    backgroundColor: '#161b22',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#30363d',
    padding: 12,
    position: 'relative',
  },
  deleteButton: {
    position: 'absolute',
    top: 8,
    right: 8,
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#0d1117',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 10,
  },
  appCardContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
    padding: 8,
  },
  appIconContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  appIconCircle: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: '#21262d',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#30363d',
  },
  appIconImage: {
    width: 56,
    height: 56,
    borderRadius: 12,
  },
  appName: {
    color: '#f0f6fc',
    fontSize: 15,
    fontWeight: '700',
    textAlign: 'center',
  },
  appCategory: {
    color: '#8b949e',
    fontSize: 11,
    fontWeight: '600',
    textAlign: 'center',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  emptyApps: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
    gap: 12,
  },
  emptyAppsText: {
    color: '#8b949e',
    fontSize: 18,
    fontWeight: '600',
  },
  emptyAppsSubtext: {
    color: '#8b949e',
    fontSize: 13,
  },
  addAppForm: {
    backgroundColor: '#161b22',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#30363d',
    padding: 16,
    marginBottom: 16,
    gap: 12,
  },
  addAppTitle: {
    color: '#f0f6fc',
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 4,
  },
  appInput: {
    backgroundColor: '#0d1117',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#30363d',
    padding: 14,
    color: '#f0f6fc',
    fontSize: 15,
  },
  appTypeSelector: {
    flexDirection: 'row',
    gap: 8,
  },
  appTypeButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    padding: 12,
    borderRadius: 10,
    backgroundColor: '#0d1117',
    borderWidth: 1,
    borderColor: '#30363d',
  },
  appTypeButtonActive: {
    backgroundColor: '#21262d',
    borderColor: '#58a6ff',
  },
  appTypeText: {
    color: '#8b949e',
    fontSize: 14,
    fontWeight: '600',
  },
  appTypeTextActive: {
    color: '#58a6ff',
  },
  addAppButtons: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 4,
  },
  addAppActionButton: {
    flex: 1,
    padding: 14,
    borderRadius: 12,
    alignItems: 'center',
  },
  cancelButton: {
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
  },
  cancelButtonText: {
    color: '#8b949e',
    fontSize: 15,
    fontWeight: '700',
  },
  saveButton: {
    backgroundColor: '#238636',
  },
  saveButtonText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '700',
  },
  dpadContainer: {
    alignItems: 'center',
    marginBottom: 24,
  },
  dpadCircle: {
    width: 240,
    height: 240,
    borderRadius: 120,
    backgroundColor: '#161b22',
    borderWidth: 2,
    borderColor: '#30363d',
    position: 'relative',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 8,
    elevation: 8,
  },
  dpadButton: {
    position: 'absolute',
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 4,
    elevation: 4,
  },
  dpadTop: {
    top: 12,
    left: 88,
  },
  dpadBottom: {
    bottom: 12,
    left: 88,
  },
  dpadLeft: {
    left: 12,
    top: 88,
  },
  dpadRight: {
    right: 12,
    top: 88,
  },
  dpadButtonText: {
    color: '#f0f6fc',
    fontSize: 28,
    fontWeight: '800',
  },
  okButton: {
    position: 'absolute',
    top: 85,
    left: 85,
    width: 70,
    height: 70,
    borderRadius: 35,
    backgroundColor: '#238636',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#238636',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.5,
    shadowRadius: 4,
    elevation: 4,
    borderWidth: 2,
    borderColor: '#2ea043',
  },
  okButtonText: {
    color: '#ffffff',
    fontSize: 18,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  pressedOk: {
    transform: [{ scale: 0.95 }],
    opacity: 0.9,
  },
  buttonGroup: {
    gap: 10,
    marginBottom: 16,
  },
  groupLabel: {
    color: '#8b949e',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    paddingLeft: 4,
  },
  actionButtonsRow: {
    flexDirection: 'row',
    gap: 10,
  },
  volumeRow: {
    flexDirection: 'row',
    gap: 12,
    alignItems: 'center',
  },
  volumeContainer: {
    gap: 12,
  },
  volumeSliderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  sliderContainer: {
    flex: 1,
    gap: 8,
  },
  sliderTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    overflow: 'hidden',
  },
  sliderFill: {
    height: '100%',
    backgroundColor: '#238636',
    borderRadius: 3,
  },
  sliderButtons: {
    flexDirection: 'row',
    gap: 8,
  },
  sliderButton: {
    flex: 1,
    height: 40,
    borderRadius: 10,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
  },
  volumeButton: {
    flex: 1,
    minHeight: 64,
    borderRadius: 16,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
  },
  muteButton: {
    backgroundColor: '#1f6feb',
    borderColor: '#1f6feb',
    flex: 1.2,
  },
  muteButtonFull: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    height: 48,
    borderRadius: 12,
    backgroundColor: '#1f6feb',
    borderWidth: 1,
    borderColor: '#1f6feb',
  },
  muteButtonText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '700',
  },
  playButtonSmall: {
    backgroundColor: '#238636',
    borderColor: '#238636',
  },
  playButtonTextSmall: {
    color: '#ffffff',
    fontWeight: '700',
  },
  actionButtonSmall: {
    flex: 1,
    minHeight: 56,
    borderRadius: 14,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  actionButtonText: {
    color: '#c9d1d9',
    fontSize: 13,
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
  fullscreenButtonSmall: {
    backgroundColor: '#21262d',
    borderColor: '#30363d',
  },
  fullscreenButtonTextSmall: {
    color: '#f0f6fc',
    fontWeight: '600',
  },
  buttonIcon: {
    marginBottom: 2,
  },
  keyboardContainer: {
    flex: 1,
    gap: 16,
  },
  keyboardInputWrapper: {
    gap: 12,
  },
  keyboardSection: {
    gap: 12,
  },
  keyboardInput: {
    minHeight: 140,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#0d1117',
    color: '#c9d1d9',
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 15,
    textAlignVertical: 'top',
  },
  sendButton: {
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 20,
  },
  specialKeysRow: {
    flexDirection: 'row',
    gap: 10,
  },
  keyButton: {
    flex: 1,
    minHeight: 54,
    borderRadius: 12,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  keyButtonText: {
    color: '#c9d1d9',
    fontSize: 13,
    fontWeight: '600',
  },
  touchpadContainer: {
    flex: 1,
    gap: 12,
    marginBottom: 12,
  },
  touchpadSurface: {
    flex: 1,
    borderRadius: 20,
    borderWidth: 2,
    borderColor: '#30363d',
    backgroundColor: '#0d1117',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 6,
  },
  touchpadInner: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  touchpadText: {
    color: '#f0f6fc',
    fontSize: 24,
    fontWeight: '700',
  },
  touchpadHint: {
    color: '#8b949e',
    fontSize: 13,
  },
  touchpadButtons: {
    flexDirection: 'row',
    gap: 12,
  },
  touchpadButton: {
    flex: 1,
    minHeight: 56,
    borderRadius: 14,
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  touchpadButtonText: {
    color: '#c9d1d9',
    fontSize: 14,
    fontWeight: '600',
  },
  tabBarContainer: {
    width: '100%',
    backgroundColor: '#161b22',
  },
  tabBar: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: '#30363d',
    backgroundColor: '#161b22',
    paddingBottom: 8,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: -2 },
    shadowOpacity: 0.3,
    shadowRadius: 4,
    elevation: 8,
  },
  tabItem: {
    flex: 1,
    paddingVertical: 12,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  tabItemActive: {
    borderTopWidth: 3,
    borderTopColor: '#238636',
    backgroundColor: '#0d1117',
  },
  tabItemText: {
    color: '#8b949e',
    fontSize: 12,
    fontWeight: '600',
  },
  tabItemTextActive: {
    color: '#238636',
    fontWeight: '700',
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
  formSectionLabel: {
    color: '#8b949e',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.4,
    marginTop: 4,
    textTransform: 'uppercase',
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
  ghostButton: {
    backgroundColor: '#21262d',
    borderWidth: 1,
    borderColor: '#30363d',
  },
  ghostButtonText: {
    color: '#c9d1d9',
    fontSize: 16,
    fontWeight: '700',
  },
  pressed: {
    opacity: 0.8,
    transform: [{ scale: 0.96 }],
  },
  menuOverlay: {
    flex: 1,
    backgroundColor: 'rgba(10, 14, 23, 0.7)',
    justifyContent: 'flex-start',
    paddingTop: 80,
    paddingHorizontal: 20,
    alignItems: 'flex-end',
  },
  menuSheet: {
    width: '100%',
    maxWidth: 320,
    borderRadius: 20,
    backgroundColor: '#161b22',
    borderWidth: 1,
    borderColor: '#30363d',
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.5,
    shadowRadius: 16,
    elevation: 16,
  },
  menuHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 20,
    paddingVertical: 16,
    backgroundColor: '#0d1117',
  },
  menuHeaderTitle: {
    color: '#f0f6fc',
    fontSize: 20,
    fontWeight: '700',
  },
  menuDivider: {
    height: 1,
    backgroundColor: '#21262d',
  },
  menuSection: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 6,
  },
  menuSectionTitle: {
    color: '#8b949e',
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 4,
  },
  systemRowLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    flex: 1,
  },
  activeBadge: {
    backgroundColor: '#238636',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  activeBadgeText: {
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '700',
  },
  systemRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#0d1117',
    paddingHorizontal: 12,
    paddingVertical: 12,
  },
  systemRowActive: {
    borderColor: '#238636',
    backgroundColor: '#132218',
  },
  systemRowText: {
    flex: 1,
    gap: 2,
  },
  systemName: {
    color: '#f0f6fc',
    fontSize: 15,
    fontWeight: '700',
  },
  systemMeta: {
    color: '#8b949e',
    fontSize: 12,
  },
  systemBadge: {
    color: '#7ee787',
    fontSize: 12,
    fontWeight: '700',
  },
  systemSwapLabel: {
    color: '#58a6ff',
    fontSize: 12,
    fontWeight: '700',
  },
  menuItem: {
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  menuItemContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  menuItemPressed: {
    backgroundColor: '#21262d',
  },
  menuItemText: {
    color: '#58a6ff',
    fontSize: 15,
    fontWeight: '600',
  },
  menuItemDangerText: {
    color: '#ff7b72',
    fontSize: 15,
    fontWeight: '600',
  },
  menuItemWarningText: {
    color: '#ffa657',
    fontSize: 15,
    fontWeight: '600',
  },
  editorOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(10, 14, 23, 0.72)',
  },
  editorSheet: {
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    backgroundColor: '#161b22',
    borderTopWidth: 1,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: '#30363d',
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 32,
    gap: 12,
  },
  editorTitle: {
    color: '#f0f6fc',
    fontSize: 22,
    fontWeight: '800',
  },
  editorSubtitle: {
    color: '#8b949e',
    fontSize: 13,
    lineHeight: 18,
    marginBottom: 4,
  },
  kodiContainer: {
    gap: 16,
  },
  kodiHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  kodiHeaderTitleWrap: {
    flex: 1,
    gap: 8,
  },
  kodiBackButton: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 4,
  },
  kodiBackButtonText: {
    color: '#58a6ff',
    fontSize: 14,
    fontWeight: '600',
  },
  kodiTitle: {
    fontSize: 28,
    fontWeight: '700',
    color: '#f0f6fc',
  },
  kodiSubtitle: {
    fontSize: 14,
    color: '#8b949e',
    marginBottom: 8,
  },
  kodiSearchWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#161b22',
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  kodiSearchInput: {
    flex: 1,
    color: '#f0f6fc',
    fontSize: 15,
    paddingVertical: 0,
  },
  kodiSearchClearButton: {
    width: 22,
    height: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  kodiLoading: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
    gap: 12,
  },
  kodiLoadingText: {
    fontSize: 16,
    color: '#58a6ff',
    fontWeight: '500',
  },
  kodiErrorContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 40,
    gap: 12,
  },
  kodiErrorText: {
    fontSize: 15,
    color: '#f85149',
    textAlign: 'center',
    paddingHorizontal: 20,
  },
  kodiRetryButton: {
    backgroundColor: '#21262d',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#30363d',
    marginTop: 8,
  },
  kodiRetryButtonText: {
    color: '#58a6ff',
    fontSize: 15,
    fontWeight: '600',
  },
  channelsGrid: {
    gap: 12,
  },
  channelCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#161b22',
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: '#30363d',
    gap: 14,
  },
  channelIconContainer: {
    width: 56,
    height: 56,
    borderRadius: 12,
    backgroundColor: '#0d1117',
    alignItems: 'center',
    justifyContent: 'center',
  },
  channelInfo: {
    flex: 1,
    gap: 4,
  },
  channelNumber: {
    fontSize: 13,
    color: '#58a6ff',
    fontWeight: '600',
  },
  channelName: {
    fontSize: 17,
    color: '#f0f6fc',
    fontWeight: '600',
  },
  channelMeta: {
    fontSize: 13,
    color: '#8b949e',
  },
  emptyKodi: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
    gap: 12,
  },
  emptyKodiText: {
    fontSize: 18,
    color: '#8b949e',
    fontWeight: '600',
  },
  emptyKodiSubtext: {
    fontSize: 14,
    color: '#8b949e',
    textAlign: 'center',
    paddingHorizontal: 20,
  },
  // Settings Modals
  settingsOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    justifyContent: 'flex-end',
  },
  settingsSheet: {
    backgroundColor: '#161b22',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: '85%',
    paddingBottom: 20,
    flex: 1,
  },
  settingsHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#30363d',
    gap: 12,
  },
  settingsTitle: {
    flex: 1,
    fontSize: 20,
    color: '#f0f6fc',
    fontWeight: '600',
  },
  settingsCloseButton: {
    padding: 4,
  },
  settingsContent: {
    padding: 20,
    flex: 1,
  },
  settingsSectionTitle: {
    fontSize: 16,
    color: '#8b949e',
    fontWeight: '600',
    marginBottom: 12,
  },
  settingsSection: {
    marginBottom: 20,
  },
  settingsLoading: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 40,
    gap: 12,
  },
  settingsLoadingText: {
    fontSize: 16,
    color: '#8b949e',
  },
  settingsEmpty: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 40,
    gap: 12,
  },
  settingsEmptyText: {
    fontSize: 16,
    color: '#8b949e',
  },
  settingsInput: {
    backgroundColor: '#0d1117',
    color: '#f0f6fc',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    borderWidth: 1,
    borderColor: '#30363d',
  },
  settingsMessage: {
    backgroundColor: '#21262d',
    padding: 12,
    borderRadius: 8,
    marginBottom: 16,
  },
  settingsMessageSuccess: {
    backgroundColor: 'rgba(63, 185, 80, 0.2)',
  },
  settingsMessageError: {
    backgroundColor: 'rgba(248, 81, 73, 0.2)',
  },
  settingsMessageText: {
    fontSize: 14,
    color: '#f0f6fc',
  },
  settingsActionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#21262d',
    padding: 14,
    borderRadius: 8,
    gap: 8,
    marginTop: 12,
  },
  settingsActionButtonText: {
    fontSize: 16,
    color: '#58a6ff',
    fontWeight: '600',
  },
  // WiFi
  networkItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#0d1117',
    padding: 14,
    borderRadius: 8,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: '#30363d',
  },
  networkItemActive: {
    borderColor: '#3fb950',
    backgroundColor: 'rgba(63, 185, 80, 0.1)',
  },
  networkItemLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    flex: 1,
  },
  networkItemText: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  networkName: {
    fontSize: 16,
    color: '#f0f6fc',
    fontWeight: '500',
  },
  networkSignal: {
    fontSize: 14,
    color: '#8b949e',
  },
  // Bluetooth
  bluetoothItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#0d1117',
    padding: 14,
    borderRadius: 8,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: '#30363d',
  },
  bluetoothItemLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    flex: 1,
  },
  bluetoothItemText: {
    gap: 4,
  },
  bluetoothName: {
    fontSize: 16,
    color: '#f0f6fc',
    fontWeight: '500',
  },
  bluetoothMac: {
    fontSize: 12,
    color: '#8b949e',
  },
  bluetoothActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  bluetoothConnectButton: {
    backgroundColor: '#238636',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  bluetoothConnectText: {
    fontSize: 14,
    color: '#ffffff',
    fontWeight: '600',
  },
  bluetoothConnectedText: {
    fontSize: 14,
    color: '#3fb950',
    fontWeight: '600',
  },
  bluetoothRemoveButton: {
    padding: 6,
  },
  // Sound
  speakerItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#0d1117',
    padding: 14,
    borderRadius: 8,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: '#30363d',
  },
  speakerItemActive: {
    borderColor: '#3fb950',
    backgroundColor: 'rgba(63, 185, 80, 0.1)',
  },
  speakerItemLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    flex: 1,
  },
  speakerName: {
    fontSize: 16,
    color: '#f0f6fc',
    fontWeight: '500',
  },
  speakerActiveBadge: {
    backgroundColor: '#3fb950',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  speakerActiveText: {
    fontSize: 12,
    color: '#ffffff',
    fontWeight: '600',
  },
  settingsSubtitle: {
    fontSize: 14,
    color: '#8b949e',
    marginBottom: 16,
  },
  appItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
    backgroundColor: '#21262d',
    borderRadius: 12,
    marginBottom: 8,
  },
  appItemLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
    gap: 12,
  },
  appItemIcon: {
    width: 24,
    height: 24,
  },
  appItemText: {
    flex: 1,
  },
  recommendedAppsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  appItemAdded: {
    backgroundColor: '#1a2332',
    borderWidth: 1,
    borderColor: '#3fb950',
  },
  appRemoveButton: {
    padding: 8,
    borderRadius: 8,
    backgroundColor: 'rgba(248, 81, 73, 0.1)',
  },
  addAppCard: {
    backgroundColor: '#161b22',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#30363d',
  },
  addAppCardTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#f0f6fc',
    marginBottom: 12,
  },
  addAppChoiceButtons: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 16,
  },
  addAppChoiceButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
    backgroundColor: '#21262d',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#30363d',
  },
  addAppChoiceButtonActive: {
    backgroundColor: 'rgba(88, 166, 255, 0.15)',
    borderColor: '#58a6ff',
  },
  addAppChoiceButtonText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#8b949e',
  },
  addAppChoiceButtonTextActive: {
    color: '#58a6ff',
  },
  recommendedAppsContainer: {
    marginTop: 16,
  },
  recommendedSectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#8b949e',
    marginBottom: 12,
    marginTop: 8,
  },
  channelThumbnailImage: {
    width: 48,
    height: 48,
    borderRadius: 8,
  },
});
