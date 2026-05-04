# Just In Engine API Documentation
This document describes the API endpoints available for interacting with the Just In Engine. The Just In Engine provides various functionalities including recording status, active channels, and error reporting.

## DNS / Adresse
- DNS: `http://mf91538:8080`
- IP: `http://10.65.79.29:8080`
- Swagger: `http://mf91538:8080/swagger-ui/index.html`

## Vigtige findings (2026-04-14)

### Naming Convention (Default)
Filnavne bygges af: `{Date}_{Time}_{Channel}` med separator `_`
- Date format: `yyMMdd` (fx `260414`)
- Time format: `HHmmss` (fx `151304`)
- Channel: kanalnavnet (fx `KAM_1`)
- Resultat: `260414_151304_KAM_1.mxf`

Prefix uden channel = `260414_151304` (dato+tid del). Audio bruger dette + track label.

### Endpoint-tilgængelighed under optagelse
| Endpoint | Under optagelse | Stoppet |
|----------|----------------|---------|
| `requestRecordingStatus` | ✅ rec=true + timecode | ✅ rec=false |
| `recordingPaths` | ✅ **Returnerer fuld sti** (pålidelig!) | ✅ tom paths[] |
| `requestCurrentFilename` | ❌ **Tom value!** | ✅ Returnerer seneste filnavn |
| `requestFilename` | ❌ Tom value (did-change=true) | ✅ |
| `requestLoadNamingConvention` | ❌ 400 "Request invalid while recording" | ✅ |
| `requestNamingConventions` | ✅ Returnerer navne-liste | ✅ |
| `activeChannels` | ✅ | ✅ |
| `errors` | ✅ | ✅ |

### Konklusion for audio filename
**`recordingPaths`** er det eneste endpoint der pålideligt giver filnavnet **under optagelse**.
Vi parser prefix fra stien: `/Volumes/NLE-External/260414_151304_KAM_1.mxf` → strip channel suffix → `260414_151304`.

`requestCurrentFilename` er ubrugelig under optagelse (altid tom). Den virker kun EFTER stop.

## API Endpoints


http://10.65.79.29:8080/ingest/requestRecordingStatus

http://10.65.79.29:8080/swagger-ui/index.html



# ingest/requestNamingConventions

curl -X 'POST' \
  'http://10.65.79.29:8080/ingest/requestNamingConventions' \
  -H 'accept: */*' \
  -H 'Content-Type: application/json' \
  -d '{
  "channel": "KAM_1"
}'
Request URL
http://10.65.79.29:8080/ingest/requestNamingConventions


Response body
Download
{
  "channel": "KAM_1",
  "name": "KAM_1",
  "naming-convention-name": [
    "Default"
  ]
}


# get errors:

curl -X 'POST' \
  'http://10.65.79.29:8080/ingest/errors' \
  -H 'accept: */*' \
  -H 'Content-Type: application/json' \
  -d '{
  "channel": "KAM_2",
  "clear": 0
}'


Outputs data:
{
  "channel": "KAM_2",
  "name": "KAM_2",
  "errors": [
    {
      "date": 797343102.915827,
      "errorCode": -8998,
      "errorDomain": "TOAErrorDomainIOKit",
      "errorUIDescription": "Dropped frames",
      "errorUserInfo": {
        "NSLocalizedDescription": "The input dropped 1 frames at 13:11:50:22"
      },
      "errorType": 2
    },
    {
      "date": 797344154.385531,
      "errorCode": -8998,
      "errorDomain": "TOAErrorDomainIOKit",
      "errorUIDescription": "Dropped frames",
      "errorUserInfo": {
        "NSLocalizedDescription": "The input dropped 1 frames at 13:29:22:08"
      },
      "errorType": 2
    },
    {
      "date": 797344154.475129,
      "errorCode": -8998,
      "errorDomain": "TOAErrorDomainIOKit",
      "errorUIDescription": "Dropped frames",
      "errorUserInfo": {
        "NSLocalizedDescription": "The input dropped 1 frames at 13:29:22:11"
      },
      "errorType": 2
    }
  ]
}



{
  "channel": "string",
  "name": "string",
  "errors": [
    {
      "errorCode": 0,
      "errorDomain": "string",
      "errorUIDescription": "string",
      "errorUserInfo": {
        "NSLocalizedDescription": "string"
      },
      "date": 0
    }
  ]
}







curl -X 'POST' \
  'http://10.65.79.29:8080/ingest/requestRecordingStatus' \
  -H 'accept: */*' \
  -H 'Content-Type: application/json' \
  -d '{
  "channel": "KAM_1"
}'

Response body
Download
```json
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
```


	
Response body
Download
{
  "rec": true,
  "frames": 9,
  "channel": "Channel1",
  "hours": 12,
  "seconds": 30,
  "options": {
    "TOAJustInEngineTimecodeSource": 0,
    "TOAJustInEngineLicenseStatus": false,
    "TOAJustInEngineRecordingMode": 1,
    "TOAJustInEngineAlternativeStartTimecodeFrames": 0,
    "TOAJustInEngineTimecodeOffset": 0,
    "TOAJustInEngineVideoSignalAvailable": true,
    "TOAJustInEngineAlternativeStopTimecodeFrames": 0,
    "TOAJustInEngineRecordingError": false,
    "TOAJustInEngineLiveCutEnabled": true,
    "TOAJustInEngineMetadataWritingOption": 1,
    "TOAJustInEngineStartTimecodeFrames": 1145179,
    "TOAJustInEngineAlternativeStartTimecodeActive": false,
    "TOAJustInEngineFramerate": 2500,
    "TOAJustInEngineAlternativeStopTimecodeActive": false
  },
  "name": "Channel1",
  "minutes": 46
}


# under recorder  - timecode == timenow everytime you hit the endpoint
Response body
Download
{
  "rec": true,
  "frames": 9,
  "channel": "Channel1",
  "hours": 12,
  "seconds": 30,
  "options": {
    "TOAJustInEngineTimecodeSource": 0,
    "TOAJustInEngineLicenseStatus": false,
    "TOAJustInEngineRecordingMode": 1,
    "TOAJustInEngineAlternativeStartTimecodeFrames": 0,
    "TOAJustInEngineTimecodeOffset": 0,
    "TOAJustInEngineVideoSignalAvailable": true,
    "TOAJustInEngineAlternativeStopTimecodeFrames": 0,
    "TOAJustInEngineRecordingError": false,
    "TOAJustInEngineLiveCutEnabled": true,
    "TOAJustInEngineMetadataWritingOption": 1,
    "TOAJustInEngineStartTimecodeFrames": 1145179,
    "TOAJustInEngineAlternativeStartTimecodeActive": false,
    "TOAJustInEngineFramerate": 2500,
    "TOAJustInEngineAlternativeStopTimecodeActive": false
  },
  "name": "Channel1",
  "minutes": 46
}



	same endpoint triggered later (same recording)
Response body
Download
{
  "rec": true,
  "frames": 23,
  "channel": "Channel1",
  "hours": 12,
  "seconds": 21,
  "options": {
    "TOAJustInEngineTimecodeSource": 0,
    "TOAJustInEngineLicenseStatus": false,
    "TOAJustInEngineRecordingMode": 1,
    "TOAJustInEngineAlternativeStartTimecodeFrames": 0,
    "TOAJustInEngineTimecodeOffset": 0,
    "TOAJustInEngineVideoSignalAvailable": true,
    "TOAJustInEngineAlternativeStopTimecodeFrames": 0,
    "TOAJustInEngineRecordingError": false,
    "TOAJustInEngineLiveCutEnabled": true,
    "TOAJustInEngineMetadataWritingOption": 1,
    "TOAJustInEngineStartTimecodeFrames": 1145179,
    "TOAJustInEngineAlternativeStartTimecodeActive": false,
    "TOAJustInEngineFramerate": 2500,
    "TOAJustInEngineAlternativeStopTimecodeActive": false
  },
  "name": "Channel1",
  "minutes": 50
}

Sådan er det ved stopped:

{
  "rec": false,
  "frames": 11,
  "channel": "Channel1",
  "hours": 15,
  "seconds": 41,
  "options": {
    "TOAJustInEngineTimecodeSource": 0,
    "TOAJustInEngineLicenseStatus": false,
    "TOAJustInEngineRecordingMode": 1,
    "TOAJustInEngineAlternativeStartTimecodeFrames": 0,
    "TOAJustInEngineTimecodeOffset": 0,
    "TOAJustInEngineVideoSignalAvailable": true,
    "TOAJustInEngineAlternativeStopTimecodeFrames": 0,
    "TOAJustInEngineRecordingError": false,
    "TOAJustInEngineLiveCutEnabled": true,
    "TOAJustInEngineMetadataWritingOption": 1,
    "TOAJustInEngineStartTimecodeFrames": 0,
    "TOAJustInEngineAlternativeStartTimecodeActive": false,
    "TOAJustInEngineFramerate": 2500,
    "TOAJustInEngineAlternativeStopTimecodeActive": false
  },
  "name": "Channel1",
  "minutes": 20
}



http://10.65.79.29:8080/ingest/activeChannels

curl -X 'GET' \
  'http://10.65.79.29:8080/ingest/activeChannels' \
  -H 'accept: */*'

```json
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
```



http://10.65.79.29:8080/ingest/errors


curl -X 'POST' \
  'http://10.65.79.29:8080/ingest/errors' \
  -H 'accept: */*' \
  -H 'Content-Type: application/json' \
  -d '{
  "channel": "KAM_4",
  "clear": 0
}'

Note: EPOC alway has wrong year in date field ; fredag d. 4. november 1994 kl. 05:30:51.578 GMT+01:00
```json
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
```




{
  "servers": [
    {
      "url": "http://10.65.79.29:8080",
      "description": "Generated server url"
    }
  ],
  "tags": [
    {
      "name": "Ingest",
      "description": "Use to control Just:In. Methods are documented below."
    }
  ],
  "openapi": "3.0.1",
  "info": {
    "title": "ToolsOnAir REST API",
    "version": "v1.0.0",
    "description": "Use for controlling ToolsOnAir products. Methods are documented below."
  },
  "paths": {
    "/ingest/requestCurrentFilename": {
      "post": {
        "operationId": "requestCurrentFilename",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RetRequestFilename"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestCurrentFilename"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/setMetadataWritingOption": {
      "post": {
        "operationId": "setMetadataWritingOption",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RecordingStatus"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/SetMetadataWritingOption"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/setMarkers": {
      "post": {
        "operationId": "setMarkers",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/SetMarkers"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/setTimecodeOffset": {
      "post": {
        "operationId": "setTimecodeOffset",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/SetTimecodeOffset"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestLoadMetadataSet": {
      "post": {
        "operationId": "requestLoadMetadataSet",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/LoadedMetadataSet"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestLoadMetadataSet"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/setScheduleEvents": {
      "post": {
        "operationId": "setScheduleEvents",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/ScheduleEvents"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/stopChannel": {
      "post": {
        "operationId": "stopChannel",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/StartStopChannel"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestAudioPreview": {
      "post": {
        "operationId": "requestAudioPreview",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestAudioPreview"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestNamingConventions": {
      "post": {
        "operationId": "requestNamingConventions",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/NamingConventions"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestNamingConventions"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/activeChannels": {
      "get": {
        "operationId": "activeChannels",
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RetChannelNames"
                }
              }
            },
            "description": "OK"
          }
        },
        "tags": [
          "Ingest"
        ]
      }
    },
    "/ingest/requestMetadataSets": {
      "post": {
        "operationId": "requestMetadataSets",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/MetadataSets"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestMetadataSets"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/setEncoderCount": {
      "post": {
        "operationId": "setEncoderCount",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/SetEncoderCount"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestCanRecord": {
      "post": {
        "operationId": "requestCanRecord",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/CanRecord"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestCanRecord"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/updatedNamingConvention": {
      "post": {
        "operationId": "updatedNamingConvention",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/LoadedNamingConvention"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/UpdateNamingConvention"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestLoadCapturePreset": {
      "post": {
        "operationId": "requestLoadCapturePreset",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RetLoadedSetting"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestLoadCapturePreset"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestScheduledRecording": {
      "post": {
        "operationId": "requestScheduledRecording",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestScheduledRecording"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestLoadDestinationPreset": {
      "post": {
        "operationId": "requestLoadDestinationPreset",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RetLoadedDestinationPreset"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestLoadDestinationPreset"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/stopRecording": {
      "post": {
        "operationId": "stopRecording",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/StopRecordingWithMetadata"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/startChannel": {
      "post": {
        "operationId": "startChannel",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/StartStopChannel"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestFilename": {
      "post": {
        "operationId": "requestFilename",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RetRequestFilename"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestFilename"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/startRecordingWithFilename": {
      "post": {
        "operationId": "startRecordingWithFilename",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestRecordingWithMetadata"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/errors": {
      "post": {
        "operationId": "errors",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorsResponse"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/ErrorsRequest"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/allChannels": {
      "get": {
        "operationId": "allChannels",
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RetChannelNames"
                }
              }
            },
            "description": "OK"
          }
        },
        "tags": [
          "Ingest"
        ]
      }
    },
    "/ingest/requestEncoderCount": {
      "post": {
        "operationId": "requestEncoderCount",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RetEncoderCount"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestEncoderCount"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestDestinationPresets": {
      "post": {
        "operationId": "requestDestinationPresets",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/DestinationPresets"
                }
              }
            },
            "description": "List of preset names for a given channel"
          },
          "400": {
            "description": "The requested channel was not found or is inactive"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestDestinationSettingFileNames"
              }
            }
          },
          "required": true
        },
        "summary": "Get destination preset names for a given channel"
      }
    },
    "/ingest/requestLoadNamingConvention": {
      "post": {
        "operationId": "requestLoadNamingConvention",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/LoadedNamingConvention"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestNamingConvention"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/updatedMetadataSet": {
      "post": {
        "operationId": "updatedMetadataSet",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RetRequestFilename"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/UpdateMetadata"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/recordingConfiguration": {
      "post": {
        "operationId": "recordingConfiguration",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RecordingConfigurationResponse"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RecordingConfigurationRequest"
              }
            }
          },
          "required": true
        },
        "summary": "Returns the current recording configuration with pairs of capture and destination presets"
      }
    },
    "/ingest/requestTimecodeSource": {
      "post": {
        "operationId": "requestTimecodeSource",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RecordingStatus"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestTimecodeSource"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/recordingPaths": {
      "post": {
        "operationId": "recordingPaths",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RecordingPathsResponse"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RecordingPathsRequest"
              }
            }
          },
          "required": true
        },
        "summary": "Returns the paths of all currently recording files with their respective capture IDs"
      }
    },
    "/ingest/cancelAlternativeStopRecording": {
      "post": {
        "operationId": "cancelAlternativeStopRecording",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/CancelAlternativeStopRecording"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/splitMovie": {
      "post": {
        "operationId": "splitMovie",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "type": "object"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/Split"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestCapturePresets": {
      "post": {
        "operationId": "requestCapturePresets",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/RetRequestSettingFileNames"
                }
              }
            },
            "description": "List of capture preset names for a given channel"
          },
          "400": {
            "description": "The requested channel was not found or is inactive"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestSettingFileNames"
              }
            }
          },
          "required": true
        },
        "summary": "Get capture preset names for a given channel"
      }
    },
    "/ingest/setRecordingMode": {
      "post": {
        "operationId": "setRecordingMode",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RecordingStatus"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/SetRecordingMode"
              }
            }
          },
          "required": true
        }
      }
    },
    "/ingest/requestRecordingStatus": {
      "post": {
        "operationId": "requestRecordingStatus",
        "tags": [
          "Ingest"
        ],
        "responses": {
          "200": {
            "content": {
              "*/*": {
                "schema": {
                  "$ref": "#/components/schemas/RecordingStatus"
                }
              }
            },
            "description": "OK"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/RequestRecordingStatus"
              }
            }
          },
          "required": true
        }
      }
    }
  },
  "components": {
    "schemas": {
      "RequestLoadMetadataSet": {
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string"
          }
        },
        "required": [
          "name"
        ],
        "type": "object",
        "xml": {
          "name": "requestLoadMetadataSet"
        }
      },
      "StopRecordingWithMetadata": {
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "metadata": {
            "$ref": "#/components/schemas/StopRecordingMetadata"
          }
        },
        "required": [
          "metadata"
        ],
        "type": "object",
        "xml": {
          "name": "stopRecordingWithMetadata"
        }
      },
      "ErrorsRequest": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string"
          },
          "clear": {
            "type": "integer",
            "format": "int32"
          }
        },
        "required": [
          "channel"
        ]
      },
      "RecordingPathsRequest": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string"
          }
        },
        "required": [
          "channel"
        ]
      },
      "CanRecord": {
        "properties": {
          "rec": {
            "type": "integer",
            "format": "int32"
          },
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "error": {
            "type": "string"
          }
        },
        "required": [
          "error"
        ],
        "type": "object",
        "xml": {
          "name": "canRecord"
        }
      },
      "RecordingConfigurationRequest": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string"
          }
        },
        "required": [
          "channel"
        ]
      },
      "RetLoadedDestinationPreset": {
        "properties": {
          "destination-preset-id": {
            "type": "integer",
            "format": "int32"
          },
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "justin-destination-preset": {
            "$ref": "#/components/schemas/JustinDestinationPreset"
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "required": [
          "justin-destination-preset"
        ],
        "type": "object",
        "xml": {
          "name": "retLoadedDestinationPreset"
        }
      },
      "UpdateMetadata": {
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "metadata-set": {
            "$ref": "#/components/schemas/MetadataSet"
          }
        },
        "required": [
          "metadata-set"
        ],
        "type": "object",
        "xml": {
          "name": "updateMetadata"
        }
      },
      "JustinDestinationPreset": {
        "properties": {
          "destination-path": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/DestinationPath"
            }
          },
          "name": {
            "type": "string"
          }
        },
        "required": [
          "name"
        ],
        "type": "object",
        "xml": {
          "name": "justinDestinationPreset"
        }
      },
      "RequestNamingConventions": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "requestNamingConventions"
        }
      },
      "Error": {
        "type": "object",
        "properties": {
          "errorCode": {
            "type": "integer",
            "format": "int32"
          },
          "errorDomain": {
            "type": "string"
          },
          "errorUIDescription": {
            "type": "string"
          },
          "errorUserInfo": {
            "type": "object",
            "properties": {
              "NSLocalizedDescription": {
                "type": "string"
              }
            }
          },
          "date": {
            "type": "number",
            "format": "double"
          }
        },
        "required": [
          "errorCode",
          "errorDomain",
          "errorUIDescription",
          "date"
        ]
      },
      "Control": {
        "type": "object",
        "properties": {
          "reset-after-record": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "attribute": true
            }
          },
          "label": {
            "type": "string"
          },
          "type": {
            "$ref": "#/components/schemas/Type"
          },
          "name": {
            "type": "string"
          },
          "required": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "attribute": true
            }
          },
          "current-value": {
            "type": "string"
          }
        },
        "required": [
          "current-value",
          "label",
          "name",
          "type"
        ]
      },
      "RequestNamingConvention": {
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string"
          }
        },
        "required": [
          "name"
        ],
        "type": "object",
        "xml": {
          "name": "requestNamingConvention"
        }
      },
      "RecordingPath": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string"
          },
          "id": {
            "type": "string"
          }
        },
        "required": [
          "path",
          "id"
        ]
      },
      "RequestLoadCapturePreset": {
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "capture-preset-id": {
            "type": "integer",
            "format": "int32"
          },
          "capture-preset-name": {
            "type": "string"
          }
        },
        "required": [
          "capture-preset-name"
        ],
        "type": "object",
        "xml": {
          "name": "requestLoadCapturePreset"
        }
      },
      "RetRequestSettingFileNames": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "preset": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "xml": {
          "name": "retRequestSettingFileNames"
        }
      },
      "MetadataSet": {
        "properties": {
          "control": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/Control"
            }
          },
          "name": {
            "type": "string"
          },
          "extension": {
            "type": "string"
          }
        },
        "required": [
          "name",
          "extension"
        ],
        "type": "object",
        "xml": {
          "name": "metadataSet"
        }
      },
      "RequestTimecodeSource": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "value": {
            "type": "integer",
            "format": "int32"
          }
        },
        "xml": {
          "name": "requestTimecodeSource"
        }
      },
      "Options": {
        "type": "object",
        "properties": {
          "toa-just-in-engine-live-cut-enabled": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineLiveCutEnabled"
            }
          },
          "toa-just-in-engine-alternative-stop-timecode-active": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineAlternativeStopTimecodeActive"
            }
          },
          "toa-just-in-engine-alternative-start-timecode-active": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineAlternativeStartTimecodeActive"
            }
          },
          "toa-just-in-engine-framerate": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineFramerate"
            }
          },
          "toa-just-in-engine-alternative-start-timecode-frames": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineAlternativeStartTimecodeFrames"
            }
          },
          "toa-just-in-engine-license-status": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineLicenseStatus"
            }
          },
          "toa-just-in-engine-audio-preview-port": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineAudioPreviewPort"
            }
          },
          "toa-just-in-engine-alternative-stop-timecode-frames": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineAlternativeStopTimecodeFrames"
            }
          },
          "toa-just-in-engine-recording-error": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineRecordingError"
            }
          },
          "toa-just-in-engine-start-timecode-frames": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineStartTimecodeFrames"
            }
          },
          "toa-just-in-engine-input-type": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineInputType"
            }
          },
          "toa-just-in-engine-is-loop-recording": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineIsLoopRecording"
            }
          },
          "toa-just-in-engine-metadata-writing-option": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineMetadataWritingOption"
            }
          },
          "toa-just-in-engine-timecode-offset": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineTimecodeOffset"
            }
          },
          "toa-just-in-engine-video-signal-available": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineVideoSignalAvailable"
            }
          },
          "toa-just-in-engine-writing-proxy": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineWritingProxy"
            }
          },
          "toa-just-in-engine-recording-mode": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineRecordingMode"
            }
          },
          "toa-just-in-engine-timecode-source": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineTimecodeSource"
            }
          }
        }
      },
      "RequestMetadataSets": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "requestMetadataSets"
        }
      },
      "RecordingPathsResponse": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "paths": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/RecordingPath"
            }
          }
        },
        "required": [
          "channel",
          "name",
          "paths"
        ]
      },
      "StartRecordingMetadata": {
        "type": "object",
        "properties": {
          "toa-just-in-engine-alternative-start-timecode-frames": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineAlternativeStartTimecodeFrames"
            }
          },
          "tal-ingest-engine-override-naming-preset": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TALIngestEngineOverrideNamingPreset"
            }
          },
          "toa-just-in-engine-alternative-start-timecode-active": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineAlternativeStartTimecodeActive"
            }
          }
        }
      },
      "RequestSettingFileNames": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "requestSettingFileNames"
        }
      },
      "RequestRecordingStatus": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string"
          }
        }
      },
      "SetMarkers": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "marker": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/Marker"
            }
          }
        },
        "xml": {
          "name": "setMarkers"
        }
      },
      "StartStopChannel": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string"
          }
        },
        "required": [
          "channel"
        ]
      },
      "RequestDestinationSettingFileNames": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "requestDestinationSettingFileNames"
        }
      },
      "CancelAlternativeStopRecording": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "cancelAlternativeStopRecording"
        }
      },
      "SetEncoderCount": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "value": {
            "type": "integer",
            "format": "int32"
          }
        },
        "xml": {
          "name": "setEncoderCount"
        }
      },
      "RetChannelNames": {
        "type": "object",
        "properties": {
          "channel-names": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        }
      },
      "NamingConvention": {
        "properties": {
          "entry": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/Entry"
            }
          },
          "global-variable": {
            "type": "string"
          },
          "counter-start": {
            "type": "integer",
            "format": "int32"
          },
          "separator-string": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "split-chunk-naming-strategy": {
            "type": "integer",
            "format": "int32"
          }
        },
        "required": [
          "global-variable",
          "name",
          "separator-string"
        ],
        "type": "object",
        "xml": {
          "name": "namingConvention"
        }
      },
      "LoadedMetadataSet": {
        "properties": {
          "metadata-set-name": {
            "type": "string"
          },
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "metadata-set": {
            "$ref": "#/components/schemas/MetadataSet"
          }
        },
        "required": [
          "metadata-set",
          "metadata-set-name"
        ],
        "type": "object",
        "xml": {
          "name": "loadedMetadataSet"
        }
      },
      "Split": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "split"
        }
      },
      "H264Settings": {
        "type": "object",
        "properties": {
          "height": {
            "type": "integer",
            "format": "int32"
          },
          "profile": {
            "type": "string"
          },
          "speed": {
            "type": "string"
          },
          "gop-size": {
            "type": "integer",
            "format": "int32"
          },
          "width": {
            "type": "integer",
            "format": "int32"
          },
          "framerate": {
            "type": "integer",
            "format": "int32"
          },
          "bitrate": {
            "type": "integer",
            "format": "int32"
          },
          "entropy": {
            "type": "string"
          },
          "allow-frame-reordering": {
            "type": "integer",
            "format": "int32"
          }
        }
      },
      "JustinCapturePreset": {
        "properties": {
          "container": {
            "type": "integer",
            "format": "int32"
          },
          "overlay-path": {
            "type": "string"
          },
          "audiochannels": {
            "type": "integer",
            "format": "int32"
          },
          "tvnorm": {
            "type": "integer",
            "format": "int32"
          },
          "videoheight": {
            "type": "integer",
            "format": "int32"
          },
          "no-hardware-encoding": {
            "type": "integer",
            "format": "int32"
          },
          "do-not-write-captions": {
            "type": "integer",
            "format": "int32"
          },
          "codec": {
            "type": "string"
          },
          "burnt-in-timecode": {
            "type": "integer",
            "format": "int32"
          },
          "overlay-top": {
            "type": "number",
            "format": "double"
          },
          "update-mxf-header-length": {
            "type": "integer",
            "format": "int32"
          },
          "name": {
            "type": "string"
          },
          "reference-movie-type": {
            "type": "integer",
            "format": "int32"
          },
          "toa-compression-component": {
            "$ref": "#/components/schemas/TOACompressionComponent"
          },
          "photo-jpeg-settings": {
            "$ref": "#/components/schemas/PhotoJPEGSettings"
          },
          "audioalignment": {
            "type": "integer",
            "format": "int32"
          },
          "overlay-left": {
            "type": "number",
            "format": "double"
          },
          "mov-writing-mode": {
            "type": "integer",
            "format": "int32"
          },
          "overlay-opacity": {
            "type": "number",
            "format": "double"
          },
          "videowidth": {
            "type": "integer",
            "format": "int32"
          },
          "loop": {
            "type": "integer",
            "format": "int32"
          },
          "burnt-in-timecode-y-pad": {
            "type": "integer",
            "format": "int32"
          },
          "timecodesource": {
            "type": "integer",
            "format": "int32"
          },
          "audio-mapping": {
            "type": "string"
          },
          "aspectratio": {
            "type": "integer",
            "format": "int32"
          },
          "h264-settings": {
            "$ref": "#/components/schemas/H264Settings"
          },
          "framerate": {
            "type": "integer",
            "format": "int32"
          },
          "burnt-in-timecode-size": {
            "type": "integer",
            "format": "int32"
          }
        },
        "required": [
          "codec",
          "name",
          "toa-compression-component"
        ],
        "type": "object",
        "xml": {
          "name": "justinCapturePreset"
        }
      },
      "RecordingConfiguration": {
        "type": "object",
        "properties": {
          "destinationPreset": {
            "type": "string"
          },
          "capturePreset": {
            "type": "string"
          }
        },
        "required": [
          "capturePreset",
          "destinationPreset"
        ]
      },
      "UpdateNamingConvention": {
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "naming-convention": {
            "$ref": "#/components/schemas/NamingConvention"
          },
          "reset-counter": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "resetCounter",
              "attribute": true
            }
          }
        },
        "required": [
          "naming-convention"
        ],
        "type": "object",
        "xml": {
          "name": "updateNamingConvention"
        }
      },
      "DestinationPresets": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "preset": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "xml": {
          "name": "destinationPresets"
        }
      },
      "SetMetadataWritingOption": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "writing-option": {
            "type": "integer",
            "format": "int32"
          }
        },
        "xml": {
          "name": "setMetadataWritingOption"
        }
      },
      "Type": {
        "type": "object",
        "properties": {
          "clazz": {
            "type": "string",
            "xml": {
              "name": "class",
              "attribute": true
            }
          },
          "default": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "item": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        }
      },
      "NamingConventions": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "naming-convention-name": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "xml": {
          "name": "namingConventions"
        }
      },
      "RequestCanRecord": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "requestCanRecord"
        }
      },
      "RequestRecordingWithMetadata": {
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "proposed-filename": {
            "type": "string"
          },
          "metadata": {
            "$ref": "#/components/schemas/StartRecordingMetadata"
          }
        },
        "required": [
          "metadata",
          "proposed-filename"
        ],
        "type": "object",
        "xml": {
          "name": "requestRecordingWithMetadata"
        }
      },
      "SetRecordingMode": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "mode": {
            "type": "integer",
            "format": "int32"
          }
        },
        "xml": {
          "name": "setRecordingMode"
        }
      },
      "RecordingConfigurationResponse": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "configurations": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/RecordingConfiguration"
            }
          }
        },
        "required": [
          "channel",
          "name",
          "configurations"
        ]
      },
      "RequestScheduledRecording": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "schedule": {
            "type": "integer",
            "format": "int32"
          }
        },
        "xml": {
          "name": "requestScheduledRecording"
        }
      },
      "RecordingStatus": {
        "properties": {
          "frames": {
            "type": "integer",
            "format": "int32"
          },
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "rec": {
            "type": "integer",
            "format": "int32"
          },
          "hours": {
            "type": "integer",
            "format": "int32"
          },
          "seconds": {
            "type": "integer",
            "format": "int32"
          },
          "options": {
            "$ref": "#/components/schemas/Options"
          },
          "minutes": {
            "type": "integer",
            "format": "int32"
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "required": [
          "options"
        ],
        "type": "object",
        "xml": {
          "name": "recordingStatus"
        }
      },
      "LoadedNamingConvention": {
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "naming-convention": {
            "$ref": "#/components/schemas/NamingConvention"
          }
        },
        "required": [
          "naming-convention"
        ],
        "type": "object",
        "xml": {
          "name": "loadedNamingConvention"
        }
      },
      "SetTimecodeOffset": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "value": {
            "type": "integer",
            "format": "int32"
          }
        },
        "xml": {
          "name": "setTimecodeOffset"
        }
      },
      "StopRecordingMetadata": {
        "type": "object",
        "properties": {
          "toa-just-in-engine-alternative-stop-timecode-active": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineAlternativeStopTimecodeActive"
            }
          },
          "toa-just-in-engine-alternative-stop-timecode-frames": {
            "type": "integer",
            "format": "int32",
            "xml": {
              "name": "TOAJustInEngineAlternativeStopTimecodeFrames"
            }
          }
        }
      },
      "RequestAudioPreview": {
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string"
          },
          "audio-channel": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "required": [
          "name"
        ],
        "type": "object",
        "xml": {
          "name": "requestAudioPreview"
        }
      },
      "RequestEncoderCount": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "requestEncoderCount"
        }
      },
      "ScheduleEvent": {
        "properties": {
          "islong": {
            "type": "integer",
            "format": "int32"
          },
          "eventendtime": {
            "type": "string"
          },
          "eventstarttime": {
            "type": "string"
          },
          "istoday": {
            "type": "integer",
            "format": "int32"
          },
          "startdate": {
            "type": "number",
            "format": "double"
          },
          "duration": {
            "type": "integer",
            "format": "int32"
          },
          "enddate": {
            "type": "number",
            "format": "double"
          },
          "uuid": {
            "type": "string"
          },
          "eventstatus": {
            "type": "string"
          },
          "eventtitle": {
            "type": "string"
          }
        },
        "required": [
          "eventendtime",
          "eventstarttime",
          "eventstatus",
          "eventtitle",
          "uuid"
        ],
        "type": "object",
        "xml": {
          "name": "scheduleEvent"
        }
      },
      "RetRequestFilename": {
        "type": "object",
        "properties": {
          "value": {
            "type": "string"
          },
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "did-change": {
            "type": "string",
            "xml": {
              "name": "didChange",
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "retRequestFilename"
        }
      },
      "ErrorsResponse": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "errors": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/Error"
            }
          }
        },
        "required": [
          "channel",
          "name",
          "errors"
        ]
      },
      "RequestCurrentFilename": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "requestCurrentFilename"
        }
      },
      "RequestFilename": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "value": {
            "type": "string"
          }
        },
        "xml": {
          "name": "requestFilename"
        }
      },
      "RetEncoderCount": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "encoder-count": {
            "type": "integer",
            "format": "int32"
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          }
        },
        "xml": {
          "name": "retEncoderCount"
        }
      },
      "RetLoadedSetting": {
        "properties": {
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "filename": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "capture-preset-id": {
            "type": "integer",
            "format": "int32"
          },
          "justin-capture-preset": {
            "$ref": "#/components/schemas/JustinCapturePreset"
          },
          "cliplength": {
            "type": "string"
          }
        },
        "required": [
          "cliplength",
          "justin-capture-preset"
        ],
        "type": "object",
        "xml": {
          "name": "retLoadedSetting"
        }
      },
      "DestinationPath": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string"
          },
          "redundancy-type": {
            "type": "integer",
            "format": "int32"
          },
          "container-type": {
            "type": "integer",
            "format": "int32"
          },
          "file-buffer-size": {
            "type": "integer",
            "format": "int32"
          },
          "path-type": {
            "type": "integer",
            "format": "int32"
          }
        },
        "required": [
          "path"
        ]
      },
      "ScheduleEvents": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "schedule-event": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/ScheduleEvent"
            }
          }
        },
        "xml": {
          "name": "scheduleEvents"
        }
      },
      "Marker": {
        "properties": {
          "uuid": {
            "type": "string"
          },
          "comment": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "frames": {
            "type": "integer",
            "format": "int32"
          }
        },
        "required": [
          "name",
          "uuid"
        ],
        "type": "object",
        "xml": {
          "name": "marker"
        }
      },
      "MetadataSets": {
        "type": "object",
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "name": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "metadata-set-name": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "xml": {
          "name": "metadataSets"
        }
      },
      "Entry": {
        "type": "object",
        "properties": {
          "type": {
            "type": "integer",
            "format": "int32"
          },
          "visible": {
            "type": "integer",
            "format": "int32"
          },
          "object-name": {
            "type": "string"
          },
          "format-string": {
            "type": "string"
          },
          "label-name": {
            "type": "string"
          },
          "current-value": {
            "type": "string"
          }
        },
        "required": [
          "current-value",
          "label-name",
          "object-name"
        ]
      },
      "RequestLoadDestinationPreset": {
        "properties": {
          "channel": {
            "type": "string",
            "xml": {
              "attribute": true
            }
          },
          "destination-preset-id": {
            "type": "integer",
            "format": "int32"
          },
          "destination-preset-name": {
            "type": "string"
          }
        },
        "required": [
          "destination-preset-name"
        ],
        "type": "object",
        "xml": {
          "name": "requestLoadDestinationPreset"
        }
      },
      "TOACompressionComponent": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "component-string": {
            "type": "integer",
            "format": "int32"
          }
        },
        "required": [
          "name"
        ]
      },
      "PhotoJPEGSettings": {
        "type": "object",
        "properties": {
          "framerate": {
            "type": "integer",
            "format": "int32"
          },
          "height": {
            "type": "integer",
            "format": "int32"
          },
          "quality-level": {
            "type": "integer",
            "format": "int32"
          },
          "width": {
            "type": "integer",
            "format": "int32"
          }
        }
      }
    }
  }
}