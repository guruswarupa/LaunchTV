export type ConnectionState = 'Disconnected' | 'Connecting...' | 'Connected' | 'Error';
export type AuthState =
  | 'Saved credentials loaded'
  | 'No saved credentials'
  | 'Authenticating...'
  | 'Authenticated'
  | 'Authentication required'
  | 'Authentication failed';

export type ConnectionConfig = {
  ipAddress: string;
  password: string;
  port: string;
  username: string;
};

export type DemoApp = {
  id: string;
  name: string;
  subtitle: string;
};

export type RepositoryState = {
  authStatus: AuthState;
  deviceName: string;
  isDemoMode: boolean;
  lastAction: string;
  lastMessage: string;
  status: ConnectionState;
  appsList?: Array<{id: string; name: string; icon?: string; kind?: string; category?: string}>;
};

export type PointerEventType = 'move' | 'tap' | 'click' | 'right_click';
export type SpecialKey = 'ENTER' | 'SPACE' | 'BACKSPACE' | 'ESCAPE' | 'TAB';

export interface RemoteRepository {
  connect(config?: Partial<ConnectionConfig>): Promise<void>;
  disconnect(): void;
  dispose(): void;
  getDemoApps(): DemoApp[];
  sendAction(action: string): void;
  sendPointerEvent(event: PointerEventType, payload?: { dx?: number; dy?: number }): void;
  sendSpecialKey(key: SpecialKey): void;
  sendText(text: string): void;
}

type RepositoryListener = (update: Partial<RepositoryState>) => void;

const DEFAULT_PORT = '8765';
const RECONNECT_DELAY_MS = 3000;

const DEMO_APPS: DemoApp[] = [
  { id: 'demo-youtube', name: 'YouTube', subtitle: 'Streaming' },
  { id: 'demo-netflix', name: 'Netflix', subtitle: 'Movies & TV' },
  { id: 'demo-kodi', name: 'Kodi', subtitle: 'Media Center' },
  { id: 'demo-browser', name: 'Browser', subtitle: 'Web Apps' },
];

export class DemoRepository implements RemoteRepository {
  constructor(private readonly emit: RepositoryListener) {}

  async connect(): Promise<void> {
    this.emit({
      authStatus: 'Authenticated',
      deviceName: 'Demo LinuxTV Device',
      isDemoMode: true,
      lastMessage: 'Demo mode is ready. Explore the remote without a server.',
      status: 'Connected',
    });
  }

  disconnect() {
    this.emit({
      authStatus: 'No saved credentials',
      deviceName: '',
      isDemoMode: false,
      lastAction: 'None',
      lastMessage: 'Demo mode closed.',
      status: 'Disconnected',
    });
  }

  dispose() {
    this.disconnect();
  }

  getDemoApps() {
    return DEMO_APPS;
  }

  sendAction(action: string) {
    const label = action.replaceAll('_', ' ');
    this.emit({
      lastAction: label,
      lastMessage: `Demo action: ${label}`,
    });
  }

  sendPointerEvent(event: PointerEventType, payload?: { dx?: number; dy?: number }) {
    if (event === 'move') {
      this.emit({
        lastMessage: `Demo pointer moved ${payload?.dx ?? 0}, ${payload?.dy ?? 0}`,
      });
      return;
    }

    const label =
      event === 'tap'
        ? 'Touchpad tap'
        : event === 'click'
          ? 'Left click'
          : 'Right click';
    this.emit({
      lastAction: label,
      lastMessage: `Demo action: ${label}`,
    });
  }

  sendSpecialKey(key: SpecialKey) {
    this.emit({
      lastAction: `Key ${key}`,
      lastMessage: `Demo key: ${key}`,
    });
  }

  sendText(text: string) {
    this.emit({
      lastAction: 'Typed text',
      lastMessage: `Demo text sent: ${text}`,
    });
  }
}

export class RealServerRepository implements RemoteRepository {
  private socket: WebSocket | null = null;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private authStatus: AuthState = 'No saved credentials';
  private pendingOutbound:
    | {
        label: string;
        message: string;
        trackLastAction: boolean;
        updateLastMessage: boolean;
      }
    | null = null;
  private latestConfig: ConnectionConfig = {
    ipAddress: '',
    password: '',
    port: DEFAULT_PORT,
    username: '',
  };
  private shouldReconnect = false;

  constructor(private readonly emit: RepositoryListener) {}

  async connect(config?: Partial<ConnectionConfig>): Promise<void> {
    this.latestConfig = {
      ...this.latestConfig,
      ...config,
      ipAddress: (config?.ipAddress ?? this.latestConfig.ipAddress).trim(),
      port: (config?.port ?? this.latestConfig.port).trim() || DEFAULT_PORT,
    };

    if (!this.latestConfig.ipAddress) {
      this.emit({
        lastMessage: 'Enter the LinuxTV IP address to finish setup.',
        status: 'Disconnected',
      });
      return;
    }

    this.clearReconnectTimer();
    this.shouldReconnect = true;
    this.pendingOutbound = null;
    this.disconnectSocket();

    const target = `${this.latestConfig.ipAddress}:${this.latestConfig.port}`;
    this.emit({
      authStatus:
        this.latestConfig.username.trim() && this.latestConfig.password
          ? 'Saved credentials loaded'
          : 'No saved credentials',
      deviceName: `LinuxTV @ ${target}`,
      isDemoMode: false,
      lastMessage: `Trying ${target}`,
      status: 'Connecting...',
    });

    try {
      const ws = new WebSocket(`ws://${target}`);
      this.socket = ws;

      ws.onopen = () => {
        this.emit({
          deviceName: `LinuxTV @ ${target}`,
          lastMessage: 'Remote session is live',
          status: 'Connected',
        });
        if (this.latestConfig.username.trim() && this.latestConfig.password) {
          void this.authenticate();
        }
      };

      ws.onclose = () => {
        this.socket = null;
        this.emit({
          lastMessage: `Waiting for LinuxTV at ${target}`,
          status: 'Disconnected',
        });
        this.scheduleReconnect();
      };

      ws.onerror = () => {
        this.emit({
          lastMessage: `Unable to reach LinuxTV at ${target}`,
          status: 'Error',
        });
      };

      ws.onmessage = (event) => {
        this.handleMessage(String(event.data));
      };
    } catch {
      this.emit({
        lastMessage: 'Failed to create WebSocket',
        status: 'Error',
      });
      this.scheduleReconnect();
    }
  }

  disconnect() {
    this.shouldReconnect = false;
    this.pendingOutbound = null;
    this.authStatus = 'No saved credentials';
    this.clearReconnectTimer();
    this.disconnectSocket();
    this.emit({
      authStatus: 'No saved credentials',
      deviceName: '',
      isDemoMode: false,
      lastAction: 'None',
      lastMessage: 'Disconnected from LinuxTV.',
      status: 'Disconnected',
    });
  }

  dispose() {
    this.disconnect();
  }

  getDemoApps() {
    return [];
  }

  sendAction(action: string) {
    this.sendPayload({ action }, action);
  }

  sendPointerEvent(event: PointerEventType, payload?: { dx?: number; dy?: number }) {
    this.sendPayload(
      { type: 'pointer', event, ...payload },
      event === 'tap' ? 'Touchpad tap' : event === 'click' ? 'Left click' : 'Right click',
      {
        queueWhenAuthNeeded: event !== 'move',
        trackLastAction: event !== 'move',
        updateLastMessage: event !== 'move',
      }
    );
  }

  sendSpecialKey(key: SpecialKey) {
    this.sendPayload({ type: 'key', key }, `Key ${key}`);
  }

  sendText(text: string) {
    this.sendPayload({ type: 'text', text }, 'Typed text');
  }

  private async authenticate() {
    const activeSocket = this.socket;
    const selectedUsername = this.latestConfig.username.trim();
    const selectedPassword = this.latestConfig.password;

    if (!selectedUsername || !selectedPassword) {
      this.authStatus = 'Authentication required';
      this.emit({
        authStatus: 'Authentication required',
        lastMessage: 'Sign in with the desktop username and password',
      });
      return false;
    }

    if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) {
      this.authStatus = 'Saved credentials loaded';
      this.emit({
        authStatus: 'Saved credentials loaded',
        lastMessage: 'Credentials saved on this phone. Waiting for LinuxTV to come online.',
      });
      return true;
    }

    this.authStatus = 'Authenticating...';
    this.emit({ authStatus: 'Authenticating...' });
    activeSocket.send(
      JSON.stringify({
        type: 'auth',
        username: selectedUsername,
        password: selectedPassword,
      })
    );
    return true;
  }

  private sendPayload(
    payload: Record<string, unknown>,
    label: string,
    options?: {
      queueWhenAuthNeeded?: boolean;
      trackLastAction?: boolean;
      updateLastMessage?: boolean;
    }
  ) {
    const {
      queueWhenAuthNeeded = true,
      trackLastAction = true,
      updateLastMessage = true,
    } = options ?? {};

    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      this.emit({ lastMessage: 'Waiting for LinuxTV to come online' });
      this.scheduleReconnect();
      return;
    }

    const message = JSON.stringify(payload);

    if (
      this.authStatus !== 'Authenticated' &&
      this.latestConfig.username.trim() &&
      this.latestConfig.password
    ) {
      this.pendingOutbound = queueWhenAuthNeeded
        ? {
            label,
            message,
            trackLastAction,
            updateLastMessage,
          }
        : null;
      if (queueWhenAuthNeeded) {
        void this.authenticate();
        return;
      }
    }

    this.socket.send(message);
    if (trackLastAction) {
      this.emit({ lastAction: label });
    }
    if (updateLastMessage) {
      this.emit({ lastMessage: `Sending ${label}` });
    }
  }

  private handleMessage(rawMessage: string) {
    try {
      const payload = JSON.parse(rawMessage) as {
        action?: string;
        apps?: Array<{id: string; name: string; icon?: string}>;
        error?: string;
        event?: string;
        key?: string;
        status?: string;
        type?: string;
      };

      if (payload.status === 'auth_ok') {
        this.authStatus = 'Authenticated';
        this.emit({
          authStatus: 'Authenticated',
          lastMessage: 'Authentication successful',
        });
        if (this.pendingOutbound && this.socket?.readyState === WebSocket.OPEN) {
          const pendingOutbound = this.pendingOutbound;
          this.pendingOutbound = null;
          this.socket.send(pendingOutbound.message);
          if (pendingOutbound.trackLastAction) {
            this.emit({ lastAction: pendingOutbound.label });
          }
          if (pendingOutbound.updateLastMessage) {
            this.emit({ lastMessage: `Sent ${pendingOutbound.label}` });
          }
        }
        return;
      }

      if (payload.status === 'auth_error') {
        this.pendingOutbound = null;
        this.authStatus = 'Authentication failed';
        this.emit({
          authStatus: 'Authentication failed',
          lastMessage: payload.error ?? 'Invalid credentials',
        });
        return;
      }

      if (payload.status === 'auth_required') {
        this.authStatus = 'Authentication required';
        this.emit({
          authStatus: 'Authentication required',
          lastMessage: 'Sign in with the desktop username and password',
        });
        if (this.latestConfig.username.trim() && this.latestConfig.password) {
          void this.authenticate();
        }
        return;
      }

      if (payload.status === 'ok') {
        this.authStatus = 'Authenticated';
        this.emit({
          authStatus: 'Authenticated',
        });

        // Handle apps list response
        if (payload.type === 'apps_list' && payload.apps) {
          this.emit({
            appsList: payload.apps as Array<{id: string; name: string; icon?: string}>,
          });
          return;
        }

        if (payload.type === 'pointer') {
          if (payload.event === 'tap') {
            this.emit({
              lastAction: 'Touchpad tap',
              lastMessage: 'Touchpad tap',
            });
          } else if (payload.event === 'click') {
            this.emit({
              lastAction: 'Left click',
              lastMessage: 'Left click',
            });
          } else if (payload.event === 'right_click') {
            this.emit({
              lastAction: 'Right click',
              lastMessage: 'Right click',
            });
          }
          return;
        }

        if (payload.type === 'text') {
          this.emit({ lastMessage: 'Typed text in the active app' });
          return;
        }

        if (payload.type === 'key') {
          const keyLabel = `Key ${payload.key ?? ''}`.trim();
          this.emit({
            lastAction: keyLabel,
            lastMessage: `Sent ${payload.key ?? 'key'}`,
          });
          return;
        }

        this.emit({ lastMessage: `Sent ${payload.action ?? 'command'}` });
        return;
      }
    } catch {
      this.emit({ lastMessage: rawMessage });
    }
  }

  private clearReconnectTimer() {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
  }

  private disconnectSocket() {
    if (!this.socket) {
      return;
    }

    this.socket.onopen = null;
    this.socket.onclose = null;
    this.socket.onerror = null;
    this.socket.onmessage = null;
    this.socket.close();
    this.socket = null;
  }

  private scheduleReconnect() {
    this.clearReconnectTimer();
    if (!this.shouldReconnect || !this.latestConfig.ipAddress.trim()) {
      return;
    }

    this.reconnectTimeout = setTimeout(() => {
      void this.connect();
    }, RECONNECT_DELAY_MS);
  }
}
