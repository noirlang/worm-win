#!/usr/bin/env python3
"""
Worm Windows Agent v0.4.0
- Uzak disk imaji alma
- WinPMEM kontrol / otomatik indirme
- Secilebilir port + hafif Tk arayuz
"""

import glob
import hashlib
import json
import os
import queue
import base64
import binascii
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    HAS_TK = True
except Exception:
    HAS_TK = False

try:
    import win32con
    import win32file
    WINDOWS = True
except ImportError:
    WINDOWS = False
    win32con = None
    win32file = None

PYWIN32_OK = WINDOWS

HOST = "0.0.0.0"
DEFAULT_PORT = 4444
WINPMEM_NAME = "go-winpmem_amd64_1.0-rc2_signed.exe"

WINPMEM_URLS = [
    "https://github.com/Velocidex/WinPmem/releases/download/v4.0.rc1/go-winpmem_amd64_1.0-rc2_signed.exe",
]


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def json_gonder(conn, veri):
    conn.sendall(json.dumps(veri, ensure_ascii=False).encode("utf-8") + b"\n")


def find_winpmem_paths(script_dir):
    return [
        os.path.join(script_dir, WINPMEM_NAME),
        WINPMEM_NAME,
        r"C:\\Forensics\\go-winpmem_amd64_1.0-rc2_signed.exe",
        r"C:\\Tools\\go-winpmem_amd64_1.0-rc2_signed.exe",
    ]


def winpmem_kontrol(script_dir):
    if not WINDOWS:
        return False, "", "Non-Windows environment"

    for yol in find_winpmem_paths(script_dir):
        if os.path.exists(yol):
            return True, yol, "WinPMEM bulundu"

    return False, "", "WinPMEM not found"


def winpmem_indir(script_dir, log_cb=None, progress_cb=None):
    if not WINDOWS:
        return False, "", "Non-Windows environment"

    hedef = os.path.join(script_dir, WINPMEM_NAME)

    def reporthook(blocknum, blocksize, totalsize):
        if not progress_cb:
            return
        if totalsize <= 0:
            progress_cb("Downloading: size unknown")
            return
        indirilen = blocknum * blocksize
        yuzde = int((indirilen * 100) / totalsize)
        progress_cb(f"Downloading: %{min(yuzde, 100)}")

    son_hata = ""
    for url in WINPMEM_URLS:
        try:
            if log_cb:
                log_cb(f"Downloading WinPMEM: {url}")
            urllib.request.urlretrieve(url, hedef, reporthook=reporthook)
            if os.path.exists(hedef) and os.path.getsize(hedef) > 0:
                if log_cb:
                    log_cb(f"WinPMEM downloaded: {hedef}")
                return True, hedef, "WinPMEM downloaded"
        except Exception as e:
            son_hata = str(e)
            if log_cb:
                log_cb(f"Download attempt failed: {e}")

    return False, "", f"WinPMEM download failed: {son_hata}"


def yonetici_yetkisi_kontrol():
    if not WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ram_boyut_al():
    if not WINDOWS:
        return 0
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
        return int(mem.ullTotalPhys)
    except Exception:
        return 0


def disk_boyut_al(disk_id):
    if not WINDOWS:
        return 0

    handle = None
    try:
        handle = win32file.CreateFile(
            f"\\\\.\\PhysicalDrive{disk_id}",
            win32con.GENERIC_READ,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
            None,
            win32con.OPEN_EXISTING,
            0,
            None,
        )
        ioctl_disk_get_length_info = 0x0007405C
        buf = win32file.DeviceIoControl(handle, ioctl_disk_get_length_info, None, 8)
        return struct.unpack("<Q", buf)[0]
    except Exception:
        return 0
    finally:
        if handle:
            win32file.CloseHandle(handle)


def disk_listele_tani():
    tani = {
        "windows_mod": WINDOWS,
        "pywin32_ok": PYWIN32_OK,
        "yonetici": yonetici_yetkisi_kontrol(),
        "errors": [],
    }

    if not WINDOWS:
        tani["mesaj"] = "pywin32 modules could not be loaded"
        return [], tani

    diskler = []
    for i in range(32):
        try:
            handle = win32file.CreateFile(
                f"\\\\.\\PhysicalDrive{i}",
                win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None,
                win32con.OPEN_EXISTING,
                0,
                None,
            )
            win32file.CloseHandle(handle)
            diskler.append({
                "id": str(i),
                "ad": f"PhysicalDrive{i}",
                "boyut": disk_boyut_al(i),
            })
        except Exception as e:
            if len(tani["errors"]) < 5:
                tani["errors"].append(f"PhysicalDrive{i}: {e}")

    tani["disk_sayisi"] = len(diskler)
    if len(diskler) == 0:
        tani["mesaj"] = "No disks found"
    else:
        tani["mesaj"] = "Disks listed"

    return diskler, tani


class AgentController:
    def __init__(self, ui=None):
        self.ui = ui
        self.sock = None
        self.running = False
        self.port = DEFAULT_PORT
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.winpmem_path = ""
        self.security_key = ""
        self.language = "tr"
        self.log_file_path = self._init_log_file()

    def cevir(self, metin):
        if not isinstance(metin, str):
            return metin

        eslemeler = [
            ("Worm Windows Agent", "Worm Windows Ajan"),
            ("Server", "Sunucu"),
            ("Connection", "Baglanti"),
            ("Security Key:", "Guvenlik Anahtari:"),
            ("Approve", "Onayla"),
            ("Reset", "Sifirla"),
            ("Start", "Baslat"),
            ("Stop", "Durdur"),
            ("Check", "Kontrol Et"),
            ("Download", "Indir"),
            ("Transfer", "Aktarim"),
            ("Transfer info appears here", "Aktarim bilgisi burada gorunur"),
            ("Log", "Gunluk"),
            ("Ready", "Hazir"),
            ("Running", "Calisiyor"),
            ("Stopped", "Durduruldu"),
            ("Startup error", "Baslatma hatasi"),
            ("Port must be between 1 and 65535", "Port 1 ile 65535 arasinda olmali"),
            ("Invalid port", "Gecersiz port"),
            ("Enter a security key to approve", "Onaylamak icin guvenlik anahtari girin"),
            ("WinPMEM status: not checked", "WinPMEM durumu: kontrol edilmedi"),
            ("WinPMEM ready:", "WinPMEM hazir:"),
            ("WinPMEM unavailable:", "WinPMEM kullanilamiyor:"),
            ("WinPMEM downloaded:", "WinPMEM indirildi:"),
            ("Download failed:", "Indirme basarisiz:"),
            ("Server started", "Sunucu basladi"),
            ("Server stopped", "Sunucu durduruldu"),
            ("Authorized connection accepted", "Yetkili baglanti kabul edildi"),
            ("Unauthorized connection rejected", "Yetkisiz baglanti reddedildi"),
            ("Key verification enabled", "Anahtar dogrulama aktif"),
            ("Key verification disabled", "Anahtar dogrulama kapali"),
            ("Key approved", "Anahtar onaylandi"),
            ("Key reset", "Anahtar sifirlandi"),
            ("Key: Disabled", "Anahtar: Kapali"),
            ("Key: Active", "Anahtar: Aktif"),
            ("Client error", "Istemci hatasi"),
            ("Unknown command", "Bilinmeyen komut"),
            ("RAM acquisition", "RAM edinimi"),
            ("File transfer", "Dosya aktarimi"),
            ("Downloading", "Indiriliyor"),
            ("Error", "Hata"),
            ("Warning", "Uyari"),
            ("Info", "Bilgi"),
        ]

        sonuc = metin
        if self.language == "en":
            for en, tr in eslemeler:
                sonuc = sonuc.replace(tr, en)
        else:
            for en, tr in eslemeler:
                sonuc = sonuc.replace(en, tr)
        return sonuc

    def _init_log_file(self):
        try:
            home = os.path.expanduser("~")
            docs = os.path.join(home, "Documents")
            if not os.path.isdir(docs):
                docs = home
            log_dir = os.path.join(docs, "Worm", "logs")
            os.makedirs(log_dir, exist_ok=True)
            dosya = datetime.now().strftime("windows_agent_%Y%m%d_%H%M%S.log")
            return os.path.join(log_dir, dosya)
        except Exception:
            return ""

    def log(self, msg):
        satir = f"[{now_str()}] {self.cevir(msg)}"
        print(satir)
        if self.log_file_path:
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(satir + "\n")
            except Exception:
                pass
        if self.ui:
            self.ui.log(satir)

    def transfer_bilgi(self, msg):
        msg = self.cevir(msg)
        if self.ui:
            self.ui.set_transfer(msg)
        else:
            print(msg)

    def winpmem_hazirla(self, auto_download=True):
        var_mi, yol, mesaj = winpmem_kontrol(self.script_dir)
        if var_mi:
            self.winpmem_path = yol
            return True, yol, mesaj

        if auto_download:
            self.log("WinPMEM not found, starting automatic download...")
            ok, yol, mesaj = winpmem_indir(
                self.script_dir,
                log_cb=self.log,
                progress_cb=self.transfer_bilgi,
            )
            if ok:
                self.winpmem_path = yol
            return ok, yol, mesaj

        return False, "", mesaj

    def start_server(self, port):
        if self.running:
            return False, "Server is already running"

        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, self.port))
        self.sock.listen(5)
        self.running = True

        threading.Thread(target=self._accept_loop, daemon=True).start()
        self.log(f"Server started: {HOST}:{self.port}")
        return True, "Server started"

    def stop_server(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.log("Server stopped")

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.sock.accept()
            except Exception:
                break
            threading.Thread(target=self._istemci_yonet, args=(conn, addr), daemon=True).start()

    def _imaj_gonder(self, conn, disk_id, parca_boyutu=4 * 1024 * 1024, is_id=None):
        handle = None
        try:
            handle = win32file.CreateFile(
                f"\\\\.\\PhysicalDrive{disk_id}",
                win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None,
                win32con.OPEN_EXISTING,
                0,
                None,
            )

            is_id = is_id or ("IMG_" + str(int(time.time())))
            toplam_boyut = disk_boyut_al(disk_id)
            if toplam_boyut <= 0:
                json_gonder(conn, {"tur": "hata", "mesaj": "Disk size could not be read"})
                return

            json_gonder(conn, {
                "durum": "ok",
                "is_id": is_id,
                "tahmini_boyut": toplam_boyut,
            })

            sha256 = hashlib.sha256()
            md5 = hashlib.md5()
            okunan = 0
            son_rapor = time.time()
            baslangic = time.time()

            json_gonder(conn, {
                "tur": "veri_basliyor",
                "is_id": is_id,
                "toplam": toplam_boyut,
            })

            while okunan < toplam_boyut:
                okunacak = min(parca_boyutu, toplam_boyut - okunan)
                hr, buf = win32file.ReadFile(handle, okunacak)
                if hr != 0 or not buf:
                    break

                conn.sendall(buf)
                sha256.update(buf)
                md5.update(buf)
                okunan += len(buf)

                simdi = time.time()
                if simdi - son_rapor >= 1:
                    yuzde = int((okunan * 100) / toplam_boyut)
                    gecen = max(simdi - baslangic, 0.001)
                    hiz_mb = (okunan / 1024 / 1024) / gecen
                    self.transfer_bilgi(
                        f"Disk transfer ({is_id}): %{yuzde} | {okunan // (1024*1024)} MB / {toplam_boyut // (1024*1024)} MB | {hiz_mb:.1f} MB/s"
                    )
                    son_rapor = simdi

            if okunan == toplam_boyut:
                json_gonder(conn, {
                    "tur": "bitti",
                    "is_id": is_id,
                    "sha256": sha256.hexdigest(),
                    "md5": md5.hexdigest(),
                })
                self.transfer_bilgi(f"Disk transfer completed ({is_id})")
            else:
                json_gonder(conn, {
                    "tur": "hata",
                    "is_id": is_id,
                    "mesaj": "Image transfer interrupted",
                    "okunan": okunan,
                    "toplam": toplam_boyut,
                })
                self.transfer_bilgi(f"Disk transfer interrupted ({is_id})")

        except Exception as e:
            json_gonder(conn, {"tur": "hata", "mesaj": str(e)})
            self.transfer_bilgi(f"Disk transfer error: {e}")
        finally:
            if handle:
                win32file.CloseHandle(handle)

    def _ram_edinim_baslat(self, conn, cikti_dosya, is_id):
        if not WINDOWS:
            json_gonder(conn, {"tur": "hata", "is_id": is_id, "mesaj": "Windows required"})
            return

        ok, yol, mesaj = self.winpmem_hazirla(auto_download=True)
        if not ok:
            json_gonder(conn, {"tur": "hata", "is_id": is_id, "mesaj": mesaj, "kod": "WINPMEM_NOT_FOUND"})
            return

        if not yonetici_yetkisi_kontrol():
            json_gonder(conn, {"tur": "hata", "is_id": is_id, "mesaj": "Administrator privileges required", "kod": "ADMIN_REQUIRED"})
            return

        toplam_ram = ram_boyut_al()
        json_gonder(conn, {"durum": "ok", "is_id": is_id, "toplam_boyut": toplam_ram, "winpmem_yol": yol})

        komut_adaylari = [
            # go-winpmem (imzali RC2) CLI
            [yol, "acquire", cikti_dosya],
            # Olasi varyasyonlar / geri uyumluluk
            [yol, "acquire", "--output", cikti_dosya],
            [yol, cikti_dosya],
            [yol, "-o", cikti_dosya, "-1"],
        ]

        self.transfer_bilgi(f"RAM acquisition started: {cikti_dosya}")

        try:
            process = None
            secilen_komut = None
            son_hata = ""

            for aday in komut_adaylari:
                try:
                    p = subprocess.Popen(aday, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    time.sleep(1)

                    if p.poll() is None:
                        process = p
                        secilen_komut = aday
                        break

                    stderr = (p.stderr.read() or b"").decode(errors="ignore")
                    son_hata = stderr.strip() or f"returncode={p.returncode}"

                    # Bayrak uyumsuzlugunda bir sonraki adayi dene.
                    if "unknown" in stderr.lower() and "flag" in stderr.lower():
                        continue

                    # Hata bayrak disi ise yine de sonraki adayi dene.
                except Exception as e:
                    son_hata = str(e)

            if process is None:
                json_gonder(conn, {
                    "tur": "hata",
                    "is_id": is_id,
                    "mesaj": f"WinPMEM command could not be started: {son_hata}",
                    "kod": "WINPMEM_CMD_ERROR",
                })
                self.transfer_bilgi("RAM acquisition failed: WinPMEM command could not be executed")
                return

            self.log(f"Selected WinPMEM command: {' '.join(secilen_komut)}")
            json_gonder(conn, {"tur": "veri_basliyor", "is_id": is_id, "toplam": toplam_ram})

            while process.poll() is None:
                if os.path.exists(cikti_dosya) and toplam_ram > 0:
                    mevcut = os.path.getsize(cikti_dosya)
                    yuzde = int((mevcut * 100) / toplam_ram)
                    # Bazi WinPMEM surumleri dosyayi erken pre-allocate edebilir.
                    # Gercek tamamlanma sadece process basariyla bittiginde 100 olmali.
                    if yuzde >= 100:
                        yuzde = 99
                    json_gonder(conn, {
                        "tur": "ilerleme",
                        "is_id": is_id,
                        "okunan": mevcut,
                        "toplam": toplam_ram,
                        "yuzde": min(yuzde, 100),
                    })
                    self.transfer_bilgi(f"RAM acquisition: %{min(yuzde, 100)}")
                time.sleep(1)

            stdout_txt = (process.stdout.read() or b"").decode(errors="ignore") if process.stdout else ""
            stderr_txt = (process.stderr.read() or b"").decode(errors="ignore") if process.stderr else ""

            if process.returncode == 0 and os.path.exists(cikti_dosya):
                sha256_hash = hashlib.sha256()
                with open(cikti_dosya, "rb") as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        sha256_hash.update(chunk)

                json_gonder(conn, {
                    "tur": "bitti",
                    "is_id": is_id,
                    "boyut": os.path.getsize(cikti_dosya),
                    "sha256": sha256_hash.hexdigest(),
                    "mesaj": "RAM acquisition completed",
                })
                self.transfer_bilgi("RAM acquisition completed")
            else:
                detay = f"returncode={process.returncode}"
                if stderr_txt.strip():
                    detay += f" | stderr: {stderr_txt.strip()}"
                if stdout_txt.strip():
                    detay += f" | stdout: {stdout_txt.strip()}"
                json_gonder(conn, {
                    "tur": "hata",
                    "is_id": is_id,
                    "mesaj": f"WinPMEM error: {detay}",
                    "kod": "WINPMEM_ERROR",
                })
                self.transfer_bilgi(f"RAM acquisition failed: {detay}")
        except Exception as e:
            json_gonder(conn, {"tur": "hata", "is_id": is_id, "mesaj": str(e), "kod": "EXCEPTION"})
            self.transfer_bilgi(f"RAM acquisition error: {e}")

    def _dosya_stream_gonder(self, conn, dosya_yolu, is_id):
        try:
            if not os.path.exists(dosya_yolu):
                json_gonder(conn, {
                    "durum": "hata",
                    "is_id": is_id,
                    "mesaj": f"File not found: {dosya_yolu}",
                })
                self.log(f"RAM file download error ({is_id}): File not found: {dosya_yolu}")
                return

            toplam = os.path.getsize(dosya_yolu)
            self.log(f"RAM file stream started ({is_id}): {dosya_yolu} ({toplam} bytes)")
            json_gonder(conn, {
                "durum": "ok",
                "is_id": is_id,
                "tahmini_boyut": toplam,
            })

            sha256 = hashlib.sha256()
            json_gonder(conn, {
                "tur": "veri_basliyor",
                "is_id": is_id,
                "toplam": toplam,
            })

            gonderilen = 0
            son_rapor = time.time()
            with open(dosya_yolu, "rb") as f:
                while True:
                    buf = f.read(1024 * 1024)
                    if not buf:
                        break
                    conn.sendall(buf)
                    sha256.update(buf)
                    gonderilen += len(buf)

                    simdi = time.time()
                    if toplam > 0 and (simdi - son_rapor >= 1 or gonderilen == toplam):
                        yuzde = int((gonderilen * 100) / toplam)
                        self.transfer_bilgi(
                            f"RAM file transfer ({is_id}): %{yuzde} | {gonderilen // (1024*1024)} MB / {toplam // (1024*1024)} MB"
                        )
                        son_rapor = simdi

            json_gonder(conn, {
                "tur": "bitti",
                "is_id": is_id,
                "sha256": sha256.hexdigest(),
                "mesaj": "File transfer completed",
            })
            self.transfer_bilgi(f"RAM file transfer completed ({is_id})")
            self.log(f"RAM file stream completed ({is_id})")
        except Exception as e:
            json_gonder(conn, {
                "tur": "hata",
                "is_id": is_id,
                "mesaj": f"File transfer error: {e}",
            })
            self.log(f"RAM file stream error ({is_id}): {e}")

    def _istemci_yonet(self, conn, addr):
        self.log(f"Connection: {addr}")
        yetkili = False

        def anahtar_coz_ve_karsilastir(mesaj):
            anahtar_b64 = mesaj.get("guvenlik_anahtar_b64")

            # Fail-closed: istemci anahtar gonderdiyse ajan tarafinda da anahtar zorunlu.
            if not self.security_key:
                if anahtar_b64:
                    return False, "Agent security key is not configured"
                return True, ""

            if not anahtar_b64:
                return False, "Security key was not provided"

            try:
                cozulmus = base64.b64decode(anahtar_b64, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                return False, "Security key base64 is invalid"

            if cozulmus != self.security_key:
                return False, "Security key mismatch"

            return True, ""

        try:
            dosya = conn.makefile("rb")
            while True:
                data = dosya.readline()
                if not data:
                    return

                try:
                    mesaj = json.loads(data.decode("utf-8").strip())
                except json.JSONDecodeError:
                    json_gonder(conn, {"durum": "hata", "mesaj": "Invalid JSON"})
                    continue

                komut = mesaj.get("komut")

                if komut == "merhaba":
                    ok, hata = anahtar_coz_ve_karsilastir(mesaj)
                    if not ok:
                        json_gonder(conn, {
                            "durum": "hata",
                            "mesaj": hata,
                            "kod": "AUTH_FAILED",
                        })
                        self.log(f"Unauthorized connection rejected: {addr} | {hata}")
                        return

                    yetkili = True
                    self.log(f"Authorized connection accepted: {addr}")
                    json_gonder(conn, {
                        "durum": "ok",
                        "sunucu": "windows-ajan",
                        "surum": "0.4",
                        "ozellikler": ["disk_imaj", "winpmem_ram", "winpmem_otomatik_indirme"],
                    })

                elif not yetkili:
                    json_gonder(conn, {
                        "durum": "hata",
                        "mesaj": "Authorization required. Authenticate with hello first.",
                        "kod": "AUTH_REQUIRED",
                    })
                    continue

                elif komut == "disk_listele":
                    diskler, tani = disk_listele_tani()
                    self.log(f"disk_listele: {tani}")

                    if not WINDOWS:
                        json_gonder(conn, {
                            "durum": "hata",
                            "mesaj": "Agent is running without pywin32. pywin32 is missing in exe package.",
                            "tani": tani,
                        })
                    elif len(diskler) == 0:
                        json_gonder(conn, {
                            "durum": "hata",
                            "mesaj": "No disk found. Check administrator privileges and security software blocking.",
                            "tani": tani,
                        })
                    else:
                        json_gonder(conn, {"durum": "ok", "diskler": diskler, "tani": tani})

                elif komut == "imaj_baslat":
                    if not WINDOWS:
                        json_gonder(conn, {
                            "durum": "hata",
                            "mesaj": "Agent is running without pywin32. Disk imaging cannot be started.",
                        })
                        continue

                    disk_id = mesaj.get("disk_id", "0")
                    parca = int(mesaj.get("parca_boyutu", 4 * 1024 * 1024))
                    is_id = mesaj.get("is_id") or ("IMG_" + str(int(time.time())))
                    self._imaj_gonder(conn, disk_id, parca, is_id)

                elif komut == "winpmem_kontrol":
                    mevcut, yol, durum = self.winpmem_hazirla(auto_download=True)
                    json_gonder(conn, {
                        "durum": "ok",
                        "winpmem_mevcut": mevcut,
                        "winpmem_yol": yol,
                        "yonetici_yetkisi": yonetici_yetkisi_kontrol(),
                        "ram_boyut": ram_boyut_al(),
                        "mesaj": durum,
                    })

                elif komut == "winpmem_indir":
                    ok, yol, durum = winpmem_indir(
                        self.script_dir,
                        log_cb=self.log,
                        progress_cb=self.transfer_bilgi,
                    )
                    if ok:
                        self.winpmem_path = yol
                    json_gonder(conn, {
                        "durum": "ok" if ok else "hata",
                        "winpmem_mevcut": ok,
                        "winpmem_yol": yol,
                        "mesaj": durum,
                    })

                elif komut == "ram_edinim_baslat":
                    is_id = mesaj.get("is_id") or ("RAM_" + str(int(time.time())))
                    cikti_dosya = mesaj.get("cikti_dosya", "memory_dump.raw")
                    self._ram_edinim_baslat(conn, cikti_dosya, is_id)

                elif komut == "ram_dosya_indir":
                    is_id = mesaj.get("is_id") or ("RAMDL_" + str(int(time.time())))
                    dosya = mesaj.get("dosya", "memory_dump.raw")
                    # Guvenlik: sadece dosya adi kabul et, dizin gecisine izin verme.
                    dosya = os.path.basename(dosya)
                    hedef = os.path.join(self.script_dir, dosya)
                    self._dosya_stream_gonder(conn, hedef, is_id)

                elif komut in {
                    "hyperv_varlik_kontrol",
                    "hyperv_vm_listele",
                    "hyperv_bellek_listele",
                    "hyperv_dosya_indir",
                }:
                    json_gonder(conn, {
                        "durum": "hata",
                        "mesaj": "Hyper-V support has been removed. Use WinPMEM.",
                    })

                else:
                    json_gonder(conn, {"durum": "hata", "mesaj": f"Unknown command: {komut}"})

        except Exception as e:
            self.log(f"Client error: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass


class AgentUI:
    def __init__(self):
        self.controller = AgentController(ui=self)
        self.root = tk.Tk()
        self.root.title("Worm Windows Agent")
        self.root.geometry("760x520")

        self.log_queue = queue.Queue()

        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.key_var = tk.StringVar(value="")
        self.lang_var = tk.StringVar(value="tr")
        self.key_status_var = tk.StringVar(value="Key: Disabled")
        self.status_var = tk.StringVar(value="Ready")
        self.transfer_var = tk.StringVar(value="Transfer info appears here")
        self.winpmem_var = tk.StringVar(value="WinPMEM status: not checked")
        self.active_key = ""

        self._build()
        self.dil_degistir()
        self._poll_log_queue()

    def _build(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        ust = ttk.LabelFrame(frm, text="Server")
        ust.pack(fill="x", pady=4)

        ttk.Label(ust, text="Port:").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        self.port_entry = ttk.Entry(ust, textvariable=self.port_var, width=12)
        self.port_entry.grid(row=0, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(ust, text="Security Key:").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        self.key_entry = ttk.Entry(ust, textvariable=self.key_var, width=24, show="*")
        self.key_entry.grid(row=1, column=1, padx=6, pady=6, sticky="w")
        self.key_onay_btn = ttk.Button(ust, text="Approve", command=self.anahtar_onayla)
        self.key_onay_btn.grid(row=1, column=2, padx=6, pady=6)
        self.key_sifirla_btn = ttk.Button(ust, text="Reset", command=self.anahtar_sifirla)
        self.key_sifirla_btn.grid(row=1, column=3, padx=6, pady=6)
        ttk.Label(ust, textvariable=self.key_status_var).grid(row=1, column=4, padx=8, pady=6, sticky="w")

        ttk.Label(ust, text="Dil / Language:").grid(row=2, column=0, padx=6, pady=6, sticky="w")
        self.lang_combo = ttk.Combobox(ust, textvariable=self.lang_var, width=10, state="readonly")
        self.lang_combo["values"] = ("tr", "en")
        self.lang_combo.grid(row=2, column=1, padx=6, pady=6, sticky="w")
        self.lang_combo.bind("<<ComboboxSelected>>", lambda _e: self.dil_degistir())

        self.start_btn = ttk.Button(ust, text="Start", command=self.server_baslat)
        self.start_btn.grid(row=0, column=2, padx=6, pady=6)
        self.stop_btn = ttk.Button(ust, text="Stop", command=self.server_durdur)
        self.stop_btn.grid(row=0, column=3, padx=6, pady=6)

        ttk.Label(ust, textvariable=self.status_var).grid(row=0, column=4, padx=8, pady=6, sticky="w")

        winpmem = ttk.LabelFrame(frm, text="WinPMEM")
        winpmem.pack(fill="x", pady=4)

        ttk.Button(winpmem, text="Check", command=self.winpmem_kontrol_et).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(winpmem, text="Download", command=self.winpmem_indir).grid(row=0, column=1, padx=6, pady=6)
        ttk.Label(winpmem, textvariable=self.winpmem_var).grid(row=0, column=2, padx=8, pady=6, sticky="w")

        transfer = ttk.LabelFrame(frm, text="Transfer")
        transfer.pack(fill="x", pady=4)
        ttk.Label(transfer, textvariable=self.transfer_var).pack(fill="x", padx=8, pady=8)

        log_box = ttk.LabelFrame(frm, text="Log")
        log_box.pack(fill="both", expand=True, pady=4)
        self.log_text = tk.Text(log_box, height=16, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

        self.root.protocol("WM_DELETE_WINDOW", self.kapat)

    def _poll_log_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log_text.insert("end", line + "\n")
                self.log_text.see("end")
        except queue.Empty:
            pass
        self.root.after(150, self._poll_log_queue)

    def log(self, line):
        self.log_queue.put(line)

    def _cevir_widget_metinleri(self, kok):
        for cocuk in kok.winfo_children():
            try:
                metin = cocuk.cget("text")
                if isinstance(metin, str) and metin:
                    cocuk.configure(text=self.controller.cevir(metin))
            except Exception:
                pass
            self._cevir_widget_metinleri(cocuk)

    def set_transfer(self, msg):
        self.transfer_var.set(msg)
        self.log(f"[TRANSFER] {msg}")

    def dil_degistir(self):
        self.controller.language = self.lang_var.get().strip() or "tr"
        self.root.title(self.controller.cevir("Worm Windows Agent"))
        self._cevir_widget_metinleri(self.root)
        self.key_status_var.set(self.controller.cevir(self.key_status_var.get()))
        self.status_var.set(self.controller.cevir(self.status_var.get()))
        self.transfer_var.set(self.controller.cevir(self.transfer_var.get()))
        self.winpmem_var.set(self.controller.cevir(self.winpmem_var.get()))

    def anahtar_onayla(self):
        key = self.key_var.get().strip()
        if not key:
            messagebox.showwarning(self.controller.cevir("Warning"), self.controller.cevir("Enter a security key to approve"))
            return

        self.active_key = key
        self.controller.security_key = key
        self.key_entry.configure(state="disabled")
        self.key_status_var.set(self.controller.cevir("Key: Active"))
        self.log(self.controller.cevir("[SECURITY] Key approved"))

    def anahtar_sifirla(self):
        self.active_key = ""
        self.controller.security_key = ""
        self.key_var.set("")
        self.key_entry.configure(state="normal")
        self.key_status_var.set(self.controller.cevir("Key: Disabled"))
        self.log(self.controller.cevir("[SECURITY] Key reset"))

    def server_baslat(self):
        try:
            port = int(self.port_var.get().strip())
            if port <= 0 or port > 65535:
                raise ValueError(self.controller.cevir("Invalid port"))
        except Exception:
            messagebox.showerror(self.controller.cevir("Error"), self.controller.cevir("Port must be between 1 and 65535"))
            return

        try:
            self.controller.language = self.lang_var.get().strip() or "tr"
            self.controller.security_key = self.active_key
            ok, msg = self.controller.start_server(port)
            if ok:
                self.status_var.set(self.controller.cevir(f"Running ({HOST}:{port})"))
                if self.controller.security_key:
                    self.log(self.controller.cevir("[SECURITY] Key verification enabled"))
                else:
                    self.log(self.controller.cevir("[SECURITY] Key verification disabled"))
            else:
                self.status_var.set(self.controller.cevir(msg))
                messagebox.showwarning(self.controller.cevir("Info"), self.controller.cevir(msg))
        except Exception as e:
            self.status_var.set(self.controller.cevir("Startup error"))
            messagebox.showerror(self.controller.cevir("Error"), self.controller.cevir(str(e)))

    def server_durdur(self):
        self.controller.stop_server()
        self.status_var.set(self.controller.cevir("Stopped"))

    def winpmem_kontrol_et(self):
        ok, yol, mesaj = self.controller.winpmem_hazirla(auto_download=True)
        if ok:
            self.winpmem_var.set(self.controller.cevir(f"WinPMEM ready: {yol}"))
        else:
            self.winpmem_var.set(self.controller.cevir(f"WinPMEM unavailable: {mesaj}"))

    def winpmem_indir(self):
        def worker():
            ok, yol, mesaj = winpmem_indir(
                self.controller.script_dir,
                log_cb=self.controller.log,
                progress_cb=self.set_transfer,
            )
            if ok:
                self.controller.winpmem_path = yol
                self.winpmem_var.set(self.controller.cevir(f"WinPMEM downloaded: {yol}"))
            else:
                self.winpmem_var.set(self.controller.cevir(f"Download failed: {mesaj}"))

        threading.Thread(target=worker, daemon=True).start()

    def kapat(self):
        self.controller.stop_server()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def run_cli():
    controller = AgentController(ui=None)
    print("Worm Windows Agent (CLI)")
    print(f"Windows mode: {WINDOWS}")
    try:
        port_text = input(f"Port [{DEFAULT_PORT}]: ").strip()
        port = int(port_text) if port_text else DEFAULT_PORT
    except Exception:
        port = DEFAULT_PORT

    key_text = input("Security key (optional): ").strip()
    controller.security_key = key_text

    ok, msg = controller.start_server(port)
    print(msg)
    if not ok:
        return

    print("Stop with Ctrl+C")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.stop_server()


def main():
    if HAS_TK:
        ui = AgentUI()
        ui.run()
    else:
        run_cli()


if __name__ == "__main__":
    main()
