# discord_vpn.py - v12
# Sekme arka planda = VPN ACIK
# Sekme KAPATILDI = VPN KAPALI
# Ag baglantisina BAKMIYOR (yanlis pozitif yok)

import subprocess
import psutil
import time
import sys
import os
import ctypes
import socket
import threading
import select
import ssl
import json
import urllib.request

class DiscordDetector:
    """
    Discord acik mi kontrol et
    - Discord uygulamasi
    - Tarayicida discord sekmesi (arka planda bile)
    - Ag baglantisina BAKMIYOR
    """

    def __init__(self):
        self.discord_names = [
            'discord.exe', 'discordcanary.exe', 'discordptb.exe'
        ]

    def is_app(self):
        """Discord uygulamasi calisiyor mu"""
        for p in psutil.process_iter(['name']):
            try:
                n = p.info['name']
                if n and n.lower() in self.discord_names:
                    return True
            except:
                continue
        return False

    def is_browser(self):
        """
        Tarayicida Discord sekmesi acik mi
        TUM pencereleri tarar (arka plan dahil)
        Chrome/Edge her sekme icin ayri pencere olusturur
        """
        try:
            user32 = ctypes.windll.user32
            found = [False]

            browsers = ['chrome', 'firefox', 'edge',
                       'opera', 'brave', 'vivaldi', 'mozilla']

            def cb(hwnd, _):
                # Gorunur OLMAYAN pencerelere de bak
                # Cunku arka plan sekmeleri gorunmez olabilir
                ln = user32.GetWindowTextLengthW(hwnd)
                if ln > 0:
                    buf = ctypes.create_unicode_buffer(ln + 1)
                    user32.GetWindowTextW(hwnd, buf, ln + 1)
                    t = buf.value.lower()

                    if 'discord' in t:
                        # Tarayici penceresi mi kontrol et
                        for b in browsers:
                            if b in t:
                                found[0] = True
                                return False  # Bulduk, dur

                        # Pencere sinif adina da bak
                        class_buf = ctypes.create_unicode_buffer(256)
                        user32.GetClassNameW(hwnd, class_buf, 256)
                        cls = class_buf.value.lower()

                        browser_classes = [
                            'chrome_widgetwin', 'mozillawindowclass',
                            'operawindowclass', 'edgewindowclass'
                        ]
                        for bc in browser_classes:
                            if bc in cls:
                                found[0] = True
                                return False

                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
            )
            user32.EnumWindows(WNDENUMPROC(cb), 0)

            if found[0]:
                return True

        except:
            pass

        # Yontem 2: Chrome/Edge process komut satirinda discord var mi
        # Chrome her sekme icin ayri process acar
        # Arka plandaki sekme bile process olarak calisir
        try:
            for proc in psutil.process_iter(['name', 'cmdline']):
                try:
                    name = proc.info['name']
                    if not name:
                        continue
                    name = name.lower()

                    # Tarayici process'i mi
                    is_browser = False
                    for b in ['chrome.exe', 'msedge.exe', 'firefox.exe',
                              'opera.exe', 'brave.exe', 'vivaldi.exe']:
                        if name == b:
                            is_browser = True
                            break

                    if not is_browser:
                        continue

                    # Komut satirinda discord var mi
                    cmdline = proc.info.get('cmdline')
                    if cmdline:
                        full = ' '.join(cmdline).lower()
                        if 'discord.com' in full or 'discordapp.com' in full:
                            return True

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except:
            pass

        # Yontem 3: Tarayici pencere basliklarini daha detayli tara
        try:
            r = subprocess.run([
                'powershell', '-Command',
                'Get-Process | Where-Object {$_.MainWindowTitle -like "*discord*"} '
                '| Select-Object -ExpandProperty MainWindowTitle'
            ], capture_output=True, text=True, timeout=5,
               creationflags=subprocess.CREATE_NO_WINDOW)

            if r.stdout.strip():
                titles = r.stdout.strip().lower()
                for b in browsers:
                    if b in titles:
                        return True
        except:
            pass

        return False

    def check(self):
        """Discord acik mi - kesin sonuc"""

        # 1. Discord uygulamasi
        if self.is_app():
            return True, "Uygulama"

        # 2. Tarayicida discord sekmesi
        if self.is_browser():
            return True, "Tarayici"

        return False, ""


class SNIProxy:
    """SNI fragmentasyon - sadece Discord domainleri"""

    def __init__(self, port=8899):
        self.port = port
        self.running = False
        self.server = None
        self.thread = None

        self.blocked_domains = [
            'discord.com', 'discordapp.com', 'discord.gg',
            'discordapp.net', 'discord.media', 'discord.new',
            'discord.gift', 'discord.gifts', 'discord.dev',
            'discordcdn.com', 'discordstatus.com', 'dis.gd',
        ]

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
            self.server.bind(('127.0.0.1', self.port))
            self.server.listen(20)
            while self.running:
                try:
                    client, _ = self.server.accept()
                    t = threading.Thread(
                        target=self._handle, args=(client,), daemon=True
                    )
                    t.start()
                except socket.timeout:
                    continue
                except:
                    break
        except:
            self.running = False

    def _is_blocked(self, host):
        host = host.lower()
        for d in self.blocked_domains:
            if host == d or host.endswith('.' + d):
                return True
        return False

    def _handle(self, client):
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

                if self._is_blocked(host):
                    self._connect_fragmented(client, host, port)
                else:
                    self._connect_direct(client, host, port)
            else:
                self._handle_http(client, data)

            try:
                client.close()
            except:
                pass
        except:
            try:
                client.close()
            except:
                pass

    def _connect_fragmented(self, client, host, port):
        try:
            ip = self._doh_resolve(host)
            if not ip:
                client.send(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
                return

            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.settimeout(10)
            remote.connect((ip, port))

            client.send(b'HTTP/1.1 200 Connection Established\r\n\r\n')

            client_hello = client.recv(16384)
            if not client_hello:
                remote.close()
                return

            if len(client_hello) > 10:
                chunk_size = 3
                for i in range(0, len(client_hello), chunk_size):
                    remote.send(client_hello[i:i + chunk_size])
                    time.sleep(0.001)
            else:
                remote.send(client_hello)

            self._relay(client, remote)
            remote.close()
        except:
            pass

    def _connect_direct(self, client, host, port):
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
        except:
            pass

    def _handle_http(self, client, data):
        try:
            request = data.decode('utf-8', errors='ignore')
            line = request.split('\n')[0]
            parts = line.split(' ')
            if len(parts) >= 2 and '://' in parts[1]:
                host = parts[1].split('://')[1].split('/')[0].split(':')[0]
                remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                remote.settimeout(10)
                try:
                    ip = socket.gethostbyname(host)
                except:
                    ip = host
                remote.connect((ip, 80))
                remote.send(data)
                self._relay(client, remote)
                remote.close()
        except:
            pass

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
            ctx = ssl.create_default_context()
            url = f"https://8.8.4.4/resolve?name={domain}&type=A"
            req = urllib.request.Request(url)
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
            bypass = (
                "<local>;"
                "*.google.com;*.google.com.tr;*.googleapis.com;*.gstatic.com;"
                "*.youtube.com;*.ytimg.com;*.googlevideo.com;*.ggpht.com;"
                "*.twitter.com;*.twimg.com;*.x.com;"
                "*.instagram.com;*.cdninstagram.com;"
                "*.facebook.com;*.fbcdn.net;"
                "*.tiktok.com;*.tiktokcdn.com;"
                "*.reddit.com;*.redd.it;*.redditmedia.com;"
                "*.github.com;*.githubusercontent.com;*.githubassets.com;"
                "*.stackoverflow.com;*.stackexchange.com;"
                "*.amazon.com;*.amazon.com.tr;"
                "*.netflix.com;*.spotify.com;*.scdn.co;"
                "*.twitch.tv;*.ttvnw.net;"
                "*.wikipedia.org;*.wikimedia.org;"
                "*.microsoft.com;*.windows.com;*.office.com;"
                "*.live.com;*.outlook.com;*.bing.com;*.msn.com;"
                "*.apple.com;*.icloud.com;"
                "*.whatsapp.com;*.whatsapp.net;"
                "*.telegram.org;*.t.me;"
                "*.steam.com;*.steampowered.com;*.steamcommunity.com;"
                "*.epicgames.com;*.riotgames.com;"
                "*.cloudflare.com;*.cloudfront.net;"
                "*.akamai.com;*.akamaized.net;*.amazonaws.com;"
                "*.hepsiburada.com;*.trendyol.com;*.n11.com;"
                "*.sahibinden.com;*.eksisozluk.com;"
                "10.*;172.16.*;192.168.*;127.*;localhost"
            )
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, bypass)
            winreg.CloseKey(key)

            internet = ctypes.windll.wininet
            internet.InternetSetOptionW(0, 39, 0, 0)
            internet.InternetSetOptionW(0, 37, 0, 0)
            return True
        except:
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
        self.proxy = SNIProxy(port=8899)
        self.connected = False
        self.interval = 4
        self.off = 0
        self.need = 5  # 5 x 4 = 20 saniye

    def log(self, m, c="w"):
        ts = time.strftime("%H:%M:%S")
        cl = {
            "g": "\033[92m", "r": "\033[91m",
            "y": "\033[93m", "c": "\033[96m", "w": "\033[97m"
        }
        print(f"\n  {cl.get(c, '')}{ts} | {m}\033[0m")

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
        ip = self.proxy._doh_resolve("discord.com")
        if ip:
            self.log(f"discord.com → {ip}", "c")
        self.proxy.start()
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

    def run(self):
        os.system('cls')
        print("""
\033[96m
  ╔════════════════════════════════════════════════════╗
  ║        DISCORD VPN v12 - KESIN FINAL               ║
  ║                                                    ║
  ║  ✓ Discord sekmesi arka planda = VPN ACIK kalir    ║
  ║  ✓ Discord sekmesi KAPATILIRSA = VPN KAPANIR       ║
  ║  ✓ Baska sekmeye gecince KAPANMAZ                  ║
  ║  ✓ Sadece Discord icin proxy                       ║
  ║  ✓ Diger siteler ETKILENMEZ                        ║
  ║                                                    ║
  ║  Ctrl+C = Durdur                                   ║
  ╚════════════════════════════════════════════════════╝
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
                        self.log("VPN baslatiliyor...", "c")
                        if self.connect():
                            self.log("VPN AKTIF!", "g")
                        else:
                            self.log("VPN baslatilamadi!", "r")
                else:
                    if self.connected:
                        self.off += 1
                        kalan = (self.need - self.off) * self.interval

                        if self.off >= self.need:
                            self.log("Discord kapandi → VPN KAPATILIYOR", "y")
                            self.disconnect()
                            self.log("VPN kapatildi.", "y")
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
            self.log("VPN kapatildi. Program kapandi.\n", "g")


if __name__ == "__main__":
    if os.name == 'nt':
        os.system('')
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