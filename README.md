<div align="center">
<img src="https://amele.noirlang.tr/amele.png" alt="Amele Logo" width="120" />

# Amele Windows Agent

![Amele Windows Agent Demo](windows.gif)
</div>

## 🇹🇷 Türkçe

Bu depo, **Amele Adli Bilişim Platformu** için geliştirilmiş Windows Agent bileşenidir. Hedef Windows sistemler üzerinde yönetici (Administrator) yetkisiyle çalışarak `\\.\PhysicalDrive` diskleri, WinPMEM RAM bellek dökümleri ve Docker konteyner delillerinin güvenli TCP soketi üzerinden ana Amele uygulamasına aktarılmasını sağlar.

- **Ana Repo:** https://github.com/noirlang/amele
- **Windows Agent Repo:** https://github.com/noirlang/amele-win
- **Web Sitesi:** https://amele.noirlang.tr

---

### Yetenekler

- **Başlatma Arayüzü & Sihirbaz:** Port (varsayılan: `4444`) ve güvenlik anahtarı/parolası yapılandırması.
- **Fiziksel Disk Edinimi:** `\\.\PhysicalDrive[0-31]` üzerinden bit-by-bit ham imaj transferi (RAW veya AFF4 format seçenekleri).
- **Canlı Hashleme:** İmaj ve RAM transferi sırasında eşzamanlı SHA-256 ve MD5 hash üretimi.
- **RAM Edinimi:** WinPMEM sürücüsü ve aracı üzerinden canlı bellek dökümü.
- **Konteyner Desteği:** Docker Desktop ve Windows konteyner yapılandırmalarının incelenmesi.

---

### Hazır EXE İndirme

```powershell
Invoke-WebRequest -Uri "https://amele.noirlang.tr/amele-win.exe" -OutFile "amele-win.exe"
```

---

### Windows'ta EXE Derleme

`amele-win.exe` Windows üzerinde derlenmelidir (Windows API ve pywin32 bağımlılıkları gerektirir).

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --windowed --name amele-win windows.py
```

Çıktı dosyası: `dist\amele-win.exe`

---

### Çalıştırma ve Ana Uygulama ile Bağlantı

1. `amele-win.exe` dosyasını **Yönetici Olarak Çalıştırın** (Run as Administrator).
2. Amele masaüstü uygulamasında **Ajan / Uzak Araçlar** ekranına geçin.
3. Hedef Windows IP, Port (`4444`) ve güvenlik token bilgilerini girerek bağlantıyı başlatın.

---

## 🇬🇧 English

This repository contains the Windows Agent component for the **Amele Digital Forensics Platform**. It runs with Administrator privileges on target Windows machines to stream `\\.\PhysicalDrive` disk images, WinPMEM memory dumps, and container evidence over secure TCP sockets.

- **Main Repo:** https://github.com/noirlang/amele
- **Windows Agent Repo:** https://github.com/noirlang/amele-win
- **Website:** https://amele.noirlang.tr

---

### Capabilities

- **Interactive Setup Wizard:** Port configuration and security token management.
- **Physical Drive Acquisition:** Raw bit-by-bit disk imaging from `\\.\PhysicalDrive[0-31]` in RAW or AFF4 formats.
- **Live Hashing:** Simultaneous on-the-fly SHA-256 and MD5 checksum computation.
- **RAM Acquisition:** Volatile memory acquisition via WinPMEM kernel driver.
- **Container Forensics:** Inspection and acquisition support for Docker Desktop environments.

---

### Download Prebuilt EXE

```powershell
Invoke-WebRequest -Uri "https://amele.noirlang.tr/amele-win.exe" -OutFile "amele-win.exe"
```

---

### Build EXE on Windows

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --windowed --name amele-win windows.py
```

Output: `dist\amele-win.exe`

---

### Run & Connect with Main App

1. Run `amele-win.exe` as **Administrator**.
2. Open the **Agent / Remote Tools** tab in Amele desktop application.
3. Enter the target Windows IP, Port (`4444`), and optional security token.
