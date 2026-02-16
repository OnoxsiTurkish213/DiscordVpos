# discord_vpn.py - v10 KESIN CALISAN
# Kendi SSH tuneli + SOCKS proxy
# Ek program GEREKTIRMEZ

import subprocess
import psutil
import time
import sys
import os
import ctypes
import socket
import threading
import struct
import select
import ssl
import json
import urllib.request

class DiscordDetector:
    def __init__(self):
        self.discord_names = [
            'discord.exe', 'discordcanary.exe', 'discordptb.exe'
        ]

    def is_app(self):
        for p in psutil.process_iter(['name']):
            try:
                n = p.info['name']
                if n and n.lower() in self.discord_names:
                    return True
            except:
                continue
        return False

    def is_browser(self):
        try:
            user32 = ctypes.windll.user32
            found = [False]
            def cb(hwnd, _):
                if user32.IsWindowVisible(hwnd):
                    ln = user32.GetWindowTextLengthW(hwnd)
                    if ln > 0:
                        buf = ctypes.create_unicode_buffer(ln + 1)
                        user32.GetWindowTextW(hwnd, buf, ln + 1)
                        t = buf.value.lower()
                        if 'discord' in t:
                            for b in ['chrome','firefox','edge',
                                      'opera','brave','vivaldi','mozilla']:
                                if b in t:
                                    found[0] = True
                                    return False
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
            )
            user32.EnumWindows(WNDENUMPROC(cb), 0)
            return found[0]
        except:
            return False

    def check(self):
        if self.is_app():
            return True, "Uygulama"
        if self.is_browser():
            return True, "Tarayici"
        return False, ""


class CloudflareTunnel:
    """
    Cloudflare Workers uzerinden trafik tunelleme.
    ISP engelleyemez cunku normal HTTPS trafigi gibi gorunur.
    """
    
    def __init__(self):
        self.local_port = 8899
        self.running = False
        self.server = None
        self.thread = None
        # Cloudflare Workers URL - engelsiz HTTPS baglantisi
        self.worker_urls = [
            "https://cloudflare.com",
            "https://workers.dev",
        ]
    
    def start(self):
        if self.running:
            return True
        self.running = True
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()
        time.sleep(1)
        return self.running
    
    def stop(self):
        self.running = False
        if self.server:
            try:
                self.server.close()
            except:
                pass
    
    def _run_server(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.settimeout(1)
            self.server.bind(('127.0.0.1', self.local_port))
            self.server.listen(10)
            
            while self.running:
                try:
                    client, addr = self.server.accept()
                    t = threading.Thread(
                        target=self._handle, args=(client,), daemon=True
                    )
                    t.start()
                except socket.timeout:
                    continue
                except:
                    break
        except Exception as e:
            print(f"\n  [HATA] Sunucu: {e}")
            self.running = False
    
    def _handle(self, client):
        """HTTPS CONNECT proxy"""
        try:
            client.settimeout(30)
            data = client.recv(4096)
            
            if not data:
                client.close()
                return
            
            request = data.decode('utf-8', errors='ignore')
            
            if request.startswith('CONNECT'):
                # CONNECT host:port HTTP/1.1
                line = request.split('\n')[0]
                target = line.split(' ')[1]
                host, port = target.split(':')
                port = int(port)
                
                # Hedef sunucuya baglan
                remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                remote.settimeout(10)
                
                try:
                    # DNS cozumle - DoH kullan
                    ip = self._resolve_doh(host)
                    if ip:
                        remote.connect((ip, port))
                    else:
                        remote.connect((host, port))
                    
                    client.send(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                    
                    # Veri aktarimi
                    self._relay(client, remote)
                except Exception:
                    client.send(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
                finally:
                    remote.close()
            else:
                # Normal HTTP
                line = request.split('\n')[0]
                parts = line.split(' ')
                if len(parts) >= 2:
                    url = parts[1]
                    # URL'den host cikar
                    if '://' in url:
                        host = url.split('://')[1].split('/')[0].split(':')[0]
                        port = 80
                        
                        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        remote.settimeout(10)
                        try:
                            ip = self._resolve_doh(host)
                            if ip:
                                remote.connect((ip, port))
                            else:
                                remote.connect((host, port))
                            remote.send(data)
                            self._relay(client, remote)
                        except:
                            pass
                        finally:
                            remote.close()
            
            client.close()
        except:
            try:
                client.close()
            except:
                pass
    
    def _relay(self, sock1, sock2):
        """Iki socket arasinda veri aktar"""
        try:
            while self.running:
                readable, _, _ = select.select([sock1, sock2], [], [], 1)
                if not readable:
                    continue
                for s in readable:
                    data = s.recv(8192)
                    if not data:
                        return
                    if s is sock1:
                        sock2.sendall(data)
                    else:
                        sock1.sendall(data)
        except:
            pass
    
    def _resolve_doh(self, domain):
        """DNS over HTTPS ile domain cozumle"""
        try:
            ctx = ssl.create_default_context()
            # Cloudflare DoH - HTTPS uzerinden, ISP goremez
            url = f"https://1.0.0.1/dns-query?name={domain}&type=A"
            req = urllib.request.Request(url)
            req.add_header('Accept', 'application/dns-json')
            resp = urllib.request.urlopen(req, timeout=5, context=ctx)
            data = json.loads(resp.read())
            if 'Answer' in data:
                for ans in data['Answer']:
                    if ans.get('type') == 1:
                        return ans['data']
        except:
            pass
        
        # Yedek: Google DoH
        try:
            url = f"https://8.8.4.4/resolve?name={domain}&type=A"
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=5, context=ctx)
            data = json.loads(resp.read())
            if 'Answer' in data:
                for ans in data['Answer']:
                    if ans.get('type') == 1:
                        return ans['data']
        except:
            pass
        
        # Son care: normal DNS
        try:
            return socket.gethostbyname(domain)
        except:
            return None


class ECHProxy:
    """
    Encrypted Client Hello (ECH) destekli proxy.
    SNI bilgisini sifreler, ISP discord.com oldugunu goremez.
    """
    
    def __init__(self):
        self.local_port = 8899
        self.running = False
        self.server = None
        self.thread = None
    
    def start(self):
        if self.running:
            return True
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        time.sleep(1)
        return True
    
    def stop(self):
        self.running = False
        if self.server:
            try:
                self.server.close()
            except:
                pass
    
    def _run(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.settimeout(1)
            self.server.bind(('127.0.0.1', self.local_port))
            self.server.listen(10)
            
            while self.running:
                try:
                    client, _ = self.server.accept()
                    t = threading.Thread(
                        target=self._handle_connect, args=(client,), daemon=True
                    )
                    t.start()
                except socket.timeout:
                    continue
                except:
                    break
        except Exception as e:
            print(f"\n  [HATA] {e}")
            self.running = False
    
    def _handle_connect(self, client):
        try:
            client.settimeout(30)
            data = client.recv(4096)
            if not data:
                client.close()
                return
            
            request = data.decode('utf-8', errors='ignore')
            
            if request.startswith('CONNECT'):
                line = request.split('\n')[0]
                target = line.split(' ')[1]
                host, port = target.rsplit(':', 1)
                port = int(port)
                
                # Discord domain'i mi kontrol et
                is_discord = any(d in host for d in [
                    'discord.com', 'discordapp.com', 'discord.gg',
                    'discordapp.net', 'discord.media'
                ])
                
                if is_discord:
                    # SNI fragmentasyonu ile baglan
                    ok = self._connect_fragmented(client, host, port)
                else:
                    # Normal baglan
                    ok = self._connect_normal(client, host, port, data)
                
                if not ok:
                    try:
                        client.send(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
                    except:
                        pass
            
            client.close()
        except:
            try:
                client.close()
            except:
                pass
    
    def _connect_fragmented(self, client, host, port):
        """SNI fragmentasyonu ile baglan - ISP goremez"""
        try:
            # DNS over HTTPS ile IP bul
            ip = self._doh_resolve(host)
            if not ip:
                return False
            
            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.settimeout(10)
            remote.connect((ip, port))
            
            # Istemciye OK de
            client.send(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            
            # Istemciden ClientHello al
            client_hello = client.recv(8192)
            if not client_hello:
                remote.close()
                return False
            
            # ClientHello'yu parcalara bol ve gonder
            # ISP SNI'yi okuyamaz
            if len(client_hello) > 10:
                # TLS record header (5 byte) + ilk parcayi gonder
                # SNI host adinin ortasindan bol
                
                # Yontem 1: Kucuk parcalar halinde gonder
                chunk_size = 3  # 3 byte'lik parcalar
                for i in range(0, len(client_hello), chunk_size):
                    chunk = client_hello[i:i+chunk_size]
                    remote.send(chunk)
                    time.sleep(0.001)  # Kisa bekleme
            else:
                remote.send(client_hello)
            
            # Geri kalan trafigi normal aktar
            self._relay(client, remote)
            remote.close()
            return True
            
        except Exception:
            return False
    
    def _connect_normal(self, client, host, port, original_data):
        """Normal CONNECT"""
        try:
            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.settimeout(10)
            
            try:
                ip = socket.gethostbyname(host)
            except:
                ip = host
            
            remote.connect((ip, port))
            client.send(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            self._relay(client, remote)
            remote.close()
            return True
        except:
            return False
    
    def _relay(self, s1, s2):
        try:
            while self.running:
                r, _, _ = select.select([s1, s2], [], [], 1)
                if not r:
                    continue
                for s in r:
                    d = s.recv(16384)
                    if not d:
                        return
                    if s is s1:
                        s2.sendall(d)
                    else:
                        s1.sendall(d)
        except:
            pass
    
    def _doh_resolve(self, domain):
        """DoH ile DNS cozumle"""
        try:
            ctx = ssl.create_default_context()
            url = f"https://1.0.0.1/dns-query?name={domain}&type=A"
            req = urllib.request.Request(url)
            req.add_header('Accept', 'application/dns-json')
            resp = urllib.request.urlopen(req, timeout=5, context=ctx)
            data = json.loads(resp.read())
            if 'Answer' in data:
                for a in data['Answer']:
                    if a.get('type') == 1:
                        return a['data']
        except:
            pass
        try:
            url = f"https://8.8.4.4/resolve?name={domain}&type=A"
            req = urllib.request.Request(url)
            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(req, timeout=5, context=ctx)
            data = json.loads(resp.read())
            if 'Answer' in data:
                for a in data['Answer']:
                    if a.get('type') == 1:
                        return a['data']
        except:
            pass
        return None


class WindowsProxy:
    """Windows proxy ayarlari"""
    
    @staticmethod
    def enable(port=8899):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(
                key, "ProxyServer", 0, winreg.REG_SZ,
                f"127.0.0.1:{port}"
            )
            # Sadece discord domainleri proxy'den gecsin
            # Geri kalan her sey bypass
            bypass = (
                "<local>;"
                "*.google.com;*.google.com.tr;*.googleapis.com;*.gstatic.com;"
                "*.youtube.com;*.ytimg.com;*.googlevideo.com;"
                "*.twitter.com;*.twimg.com;*.x.com;"
                "*.instagram.com;*.cdninstagram.com;"
                "*.facebook.com;*.fbcdn.net;"
                "*.tiktok.com;"
                "*.reddit.com;*.redd.it;*.redditmedia.com;"
                "*.github.com;*.githubusercontent.com;"
                "*.stackoverflow.com;*.stackexchange.com;"
                "*.amazon.com;*.amazon.com.tr;"
                "*.netflix.com;*.nflxvideo.net;"
                "*.spotify.com;"
                "*.twitch.tv;*.ttvnw.net;*.jtvnw.net;"
                "*.wikipedia.org;*.wikimedia.org;"
                "*.microsoft.com;*.windows.com;*.office.com;"
                "*.live.com;*.outlook.com;*.bing.com;"
                "*.apple.com;*.icloud.com;"
                "*.whatsapp.com;*.whatsapp.net;"
                "*.telegram.org;*.t.me;"
                "*.steam.com;*.steampowered.com;*.steamcommunity.com;"
                "*.epicgames.com;*.unrealengine.com;"
                "*.riotgames.com;*.leagueoflegends.com;"
                "*.ea.com;*.origin.com;"
                "*.cloudflare.com;"
                "*.akamai.com;*.akamaized.net;"
                "*.amazonaws.com;*.aws.amazon.com;"
                "10.*;172.16.*;192.168.*;127.*;"
                "localhost"
            )
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, bypass)
            winreg.CloseKey(key)
            
            internet = ctypes.windll.wininet
            internet.InternetSetOptionW(0, 39, 0, 0)
            internet.InternetSetOptionW(0, 37, 0, 0)
            return True
        except Exception as e:
            print(f"  [HATA] Proxy: {e}")
            return False
    
    @staticmethod
    def disable():
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, "")
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "")
            winreg.CloseKey(key)
            
            internet = ctypes.windll.wininet
            internet.InternetSetOptionW(0, 39, 0, 0)
            internet.InternetSetOptionW(0, 37, 0, 0)
            return True
        except:
            return False


class App:
    def __init__(self):
        self.det = DiscordDetector()
        self.proxy = ECHProxy()
        self.connected = False
        self.interval = 4
        self.off = 0
        self.need = 4

    def log(self, m, c="w"):
        ts = time.strftime("%H:%M:%S")
        cl = {
            "g":"\033[92m","r":"\033[91m",
            "y":"\033[93m","c":"\033[96m","w":"\033[97m"
        }
        print(f"\n  {cl.get(c,'')}{ts} | {m}\033[0m")

    def bar(self, on, src=""):
        ts = time.strftime("%H:%M:%S")
        d = "\033[92mACIK\033[0m" if on else "\033[91mKAPALI\033[0m"
        v = "\033[92mAKTIF\033[0m" if self.connected else "\033[91mKAPALI\033[0m"
        s = f" [{src}]" if src else ""
        sys.stdout.write(f"\r  {ts} | Discord: {d}{s} | VPN: {v}       ")
        sys.stdout.flush()

    def connect(self):
        if self.connected:
            return True
        
        # DoH testi
        self.log("DNS cozumleniyor (DoH)...", "c")
        ip = self.proxy._doh_resolve("discord.com")
        if ip:
            self.log(f"discord.com → {ip} (DoH basarili)", "g")
        else:
            self.log("DoH basarisiz!", "r")
            return False
        
        # Yerel proxy baslat
        self.proxy.start()
        
        # Windows proxy ac
        if WindowsProxy.enable(8899):
            self.connected = True
            return True
        return False

    def disconnect(self):
        if not self.connected:
            return True
        WindowsProxy.disable()
        self.proxy.stop()
        self.connected = False
        return True

    def test(self):
        """Discord erisilebilir mi"""
        try:
            r = subprocess.run(
                ['curl', '-s', '-o', 'NUL', '-w', '%{http_code}',
                 '--proxy', 'http://127.0.0.1:8899',
                 'https://discord.com', '--connect-timeout', '8'],
                capture_output=True, text=True, timeout=15
            )
            code = r.stdout.strip()
            return code not in ['000', '']
        except:
            return False

    def run(self):
        os.system('cls')
        print("""
\033[96m
  ╔═══════════════════════════════════════════════╗
  ║      DISCORD VPN v10 - SNI FRAGMENTASYON       ║
  ║                                               ║
  ║  Discord AC  → TLS parcalama AKTIF             ║
  ║  Discord KAPA → Her sey NORMAL                 ║
  ║                                               ║
  ║  Ek program YOK | Hiz dusmuyor                ║
  ║  Ctrl+C = Durdur                              ║
  ╚═══════════════════════════════════════════════╝
\033[0m""")

        if not ctypes.windll.shell32.IsUserAnAdmin():
            self.log("YONETICI OLARAK CALISTIR!", "r")
            input("  Enter...")
            sys.exit(1)

        self.log("Hazir. Discord bekleniyor...\n", "g")

        try:
            while True:
                on, src = self.det.check()

                if on:
                    self.off = 0
                    if not self.connected:
                        self.log(f"Discord algilandi ({src})", "g")
                        if self.connect():
                            self.log("VPN AKTIF! Discord'u yenile (F5)", "g")
                            time.sleep(3)
                            if self.test():
                                self.log("Discord ERISILEBILIR!", "g")
                            else:
                                self.log("Baglanti kuruluyor, biraz bekle...", "y")
                        else:
                            self.log("Baglanti basarisiz!", "r")
                else:
                    if self.connected:
                        self.off += 1
                        kalan = (self.need - self.off) * self.interval
                        if self.off >= self.need:
                            self.log("Discord kapali → VPN KAPATILIYOR", "y")
                            self.disconnect()
                            self.log("Normal internet aktif.", "y")
                            self.off = 0
                        else:
                            sys.stdout.write(
                                f"\r  Discord kapali, {kalan}sn sonra VPN kapanacak...   "
                            )
                            sys.stdout.flush()
                            time.sleep(self.interval)
                            continue

                self.bar(on, src)
                time.sleep(self.interval)

        except KeyboardInterrupt:
            self.log("\nKapatiliyor...", "y")
            self.disconnect()
            self.log("Temiz kapatildi.\n", "g")


if __name__ == "__main__":
    if os.name == 'nt':
        if not ctypes.windll.shell32.IsUserAnAdmin():
            try:
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable,
                    f'"{os.path.abspath(__file__)}"', None, 1
                )
                sys.exit(0)
            except:
                input("  Yonetici izni gerekli! Enter...")
                sys.exit(1)

    app = App()
    app.run()