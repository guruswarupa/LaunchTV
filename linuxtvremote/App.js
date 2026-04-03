import React, { useState, useEffect, useRef } from 'react';
import { StyleSheet, Text, View, Pressable, TextInput, Alert } from 'react-native';

export default function App() {
  const [ip, setIp] = useState('192.168.1.100:8765');
  const [status, setStatus] = useState('Disconnected');
  const ws = useRef(null);

  const connect = () => {
    if (!ip) {
      Alert.alert('Enter TV IP and port');
      return;
    }

    if (ws.current) {
      ws.current.close();
    }

    try {
      setStatus('Connecting...');
      ws.current = new WebSocket(`ws://${ip}`);

      ws.current.onopen = () => setStatus('Connected');
      ws.current.onclose = () => setStatus('Disconnected');
      ws.current.onerror = (err) => {
        console.warn('WS error', err);
        setStatus('Error');
      };
      ws.current.onmessage = (msg) => {
        console.log('WS message', msg.data);
      };
    } catch (e) {
      console.warn('Failed to open WS', e);
      setStatus('Error');
    }
  };

  const sendAction = (action) => {
    if (ws.current && ws.current.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify({ action }));
    } else {
      Alert.alert('Not connected', 'Press Connect first');
    }
  };

  useEffect(() => {
    return () => {
      if (ws.current) {
        ws.current.close();
      }
    };
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>LinuxTV Remote</Text>
      <Text style={[styles.subtitle, status === 'Connected' ? styles.online : styles.offline]}>{status}</Text>
      <TextInput
        style={styles.input}
        onChangeText={setIp}
        value={ip}
        placeholder="TV IP:port (e.g. 192.168.1.100:8765)"
        placeholderTextColor="#aaa"
        keyboardType="url"
      />
      <Pressable style={styles.connectBtn} onPress={connect}>
        <Text style={styles.connectText}>Connect</Text>
      </Pressable>

      <View style={styles.padRow}>
        <Pressable style={styles.padBtn} onPress={() => sendAction('UP')}><Text style={styles.btnText}>▲</Text></Pressable>
      </View>
      <View style={styles.padRow}>
        <Pressable style={styles.padBtn} onPress={() => sendAction('LEFT')}><Text style={styles.btnText}>◀</Text></Pressable>
        <Pressable style={styles.okBtn} onPress={() => sendAction('SELECT')}><Text style={styles.btnText}>OK</Text></Pressable>
        <Pressable style={styles.padBtn} onPress={() => sendAction('RIGHT')}><Text style={styles.btnText}>▶</Text></Pressable>
      </View>
      <View style={styles.padRow}>
        <Pressable style={styles.padBtn} onPress={() => sendAction('DOWN')}><Text style={styles.btnText}>▼</Text></Pressable>
      </View>

      <View style={styles.rowBottom}>
        <Pressable style={styles.smallBtn} onPress={() => sendAction('BACK')}><Text style={styles.smallText}>BACK</Text></Pressable>
        <Pressable style={styles.smallBtn} onPress={() => sendAction('HOME')}><Text style={styles.smallText}>HOME</Text></Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0c0f17', alignItems: 'center', justifyContent: 'flex-start', paddingTop: 60},
  title: {fontSize: 28, color: '#fff', marginBottom: 8, fontWeight: '700'},
  subtitle: {fontSize: 16, marginBottom: 16},
  online: {color: '#1eb300'},
  offline: {color: '#ff4757'},
  input: {width: '90%', height: 48, borderColor: '#3a3f53', borderWidth: 1, borderRadius: 12, color: '#fff', paddingHorizontal: 12, marginBottom: 12},
  connectBtn: {width: '60%', height: 44, backgroundColor: '#2a71ff', borderRadius: 12, justifyContent: 'center', alignItems: 'center', marginBottom: 28},
  connectText: {color: '#fff', fontSize: 16, fontWeight: '700'},
  padRow: {flexDirection: 'row', justifyContent: 'center', width: '100%', marginVertical: 8},
  padBtn: {width: 90, height: 90, borderRadius: 45, backgroundColor: '#1e2537', justifyContent: 'center', alignItems: 'center', marginHorizontal: 8},
  okBtn: {width: 100, height: 100, borderRadius: 50, backgroundColor: '#3170e8', justifyContent: 'center', alignItems: 'center', marginHorizontal: 8},
  btnText: {fontSize: 28, color: '#fff', fontWeight: 'bold'},
  rowBottom: {flexDirection: 'row', marginTop: 24},
  smallBtn: {paddingHorizontal: 14, paddingVertical: 10, borderRadius: 10, backgroundColor: '#2d3446', marginHorizontal: 10},
  smallText: {color: '#fff', fontSize: 15, fontWeight: '600'},
});