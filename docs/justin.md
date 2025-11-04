
# Just In Engine API Documentation
This document describes the API endpoints available for interacting with the Just In Engine. The Just In Engine provides various functionalities including recording status, active channels, and error reporting.

## API Endpoints


http://10.65.79.29:8080/ingest/requestRecordingStatus

Response body
Download
{
  "rec": false,
  "frames": 11,
  "channel": "KAM_1",
  "hours": 0,
  "seconds": 47,
  "options": {
    "TOAJustInEngineTimecodeSource": 6,
    "TOAJustInEngineLicenseStatus": true,
    "TOAJustInEngineRecordingMode": 1,
    "TOAJustInEngineAlternativeStartTimecodeFrames": 0,
    "TOAJustInEngineTimecodeOffset": 0,
    "TOAJustInEngineVideoSignalAvailable": true,
    "TOAJustInEngineAlternativeStopTimecodeFrames": 0,
    "TOAJustInEngineRecordingError": false,
    "TOAJustInEngineLiveCutEnabled": false,
    "TOAJustInEngineMetadataWritingOption": 1,
    "TOAJustInEngineStartTimecodeFrames": 0,
    "TOAJustInEngineAlternativeStartTimecodeActive": false,
    "TOAJustInEngineFramerate": 2500,
    "TOAJustInEngineAlternativeStopTimecodeActive": false
  },
  "name": "KAM_1",
  "minutes": 24
}


http://10.65.79.29:8080/ingest/activeChannels
{
  "channel-names": [
    "KAM_1",
    "KAM_2",
    "KAM_3",
    "KAM_4",
    "KAM_5",
    "KAM_6",
    "KAM_7",
    "KAM_8"
  ]
}



http://10.65.79.29:8080/ingest/errors
Note: EPOC alway has wrong year in date field ; fredag d. 4. november 1994 kl. 05:30:51.578 GMT+01:00
{
  "channel": "KAM_4",
  "name": "KAM_4",
  "errors": [
    {
      "date": 783923451.578716,  
      "errorCode": -8995,
      "errorDomain": "TOAErrorDomainGeneric",
      "errorUIDescription": "No signal",
      "errorUserInfo": {
        "NSLocalizedDescription": "No signal, please check the incoming video format."
      },
      "errorType": 3
    }
  ]
}