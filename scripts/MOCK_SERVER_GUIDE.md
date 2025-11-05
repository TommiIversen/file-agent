# Enhanced Mock Justin Server

## 🚀 Nye Features

Mock serveren har nu to modes:

### 🔄 Auto Mode (Standard)
- Starter automatisk når serveren startes
- Cykler mellem forskellige tilstande hver 4. sekund:
  1. **Alle kanaler OFF** (4 sek)
  2. **Alle kanaler ON** (4 sek)  
  3. **KAM_8 OFF, resten ON** (4 sek)
  4. **Ingen fejl** (4 sek)
  5. **1 random fejl** (4 sek)
  6. **2 random fejl** (4 sek)
- Total cycle: 24 sekunder

### 🎛️ Manual Mode (Ny!)
- Aktiveres automatisk når du bruger start/stop kommandoer
- Auto-cycling stoppes permanent 
- Du kan nu manuelt styre hvilke kanaler der skal være ON/OFF
- Perfekt til at teste start/stop all funktionaliteten

## 📡 API Endpoints

### Eksisterende Just In Engine API
- `GET /ingest/activeChannels` - Få alle kanaler
- `POST /ingest/requestRecordingStatus` - Få status for en kanal
- `POST /ingest/errors` - Få fejl for en kanal

### Nye Manual Control API
- `POST /ingest/startChannel` - Start en kanal (skifter til manual mode)
- `POST /ingest/stopChannel` - Stop en kanal (skifter til manual mode)

### Debug/Helper API
- `GET /mock/status` - Se mock server status og mode
- `POST /mock/reset-auto-mode` - Reset til auto-cycling mode

## 🎮 Hvordan man bruger det

### Scenario 1: Test Auto-cycling (standard)
```bash
# Start mock server
python scripts/mock_justin_server.py

# Kør test for at se auto-cycling
python scripts/test_mock_server.py
```

### Scenario 2: Test Manual Control
```bash
# Start en kanal (skifter til manual mode)
curl -X POST http://localhost:8080/ingest/startChannel \
  -H "Content-Type: application/json" \
  -d '{"channel": "KAM_1"}'

# Nu er auto-cycling stoppet og du kan kontrollere manuelt
curl -X POST http://localhost:8080/ingest/stopChannel \
  -H "Content-Type: application/json" \
  -d '{"channel": "KAM_1"}'
```

### Scenario 3: Test Start/Stop All funktionalitet
```bash
# Skift til manual mode først (start en kanal)
curl -X POST http://localhost:8080/ingest/startChannel \
  -H "Content-Type: application/json" \
  -d '{"channel": "KAM_1"}'

# Nu kan du teste bulk start/stop operations
curl -X POST http://localhost:8000/api/ingest/start-all-channels

curl -X POST http://localhost:8000/api/ingest/stop-all-channels
```

## 🔧 Debug Commands

```bash
# Se nuværende status
curl http://localhost:8080/mock/status

# Reset til auto-mode (hvis du vil tilbage)
curl -X POST http://localhost:8080/mock/reset-auto-mode
```

## 💡 Tips

1. **Start i Auto Mode**: God til at se general functionality og error cycles
2. **Skift til Manual Mode**: Perfekt til at teste dine start/stop all knapper
3. **Use Debug Endpoints**: Tjek status og reset hvis nødvendigt
4. **Port 8080**: Mock server kører på samme port som rigtige Just In Engine

## 🎯 Best Practice Workflow

1. Start mock server: `python scripts/mock_justin_server.py`
2. Lad den cycle nogle runder (se console output)
3. Test en start command for at skifte til manual mode
4. Test nu dine start/stop all funktioner
5. Reset til auto mode hvis du vil se cycling igen