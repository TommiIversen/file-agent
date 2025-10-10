@echo off
REM File Growth Simulator - Template System Test

echo Starter File Growth Simulator med Template System filnavne...
echo.
echo Konfiguration:
echo - 6 video streams (mixed types)
echo - Skriver hver 500ms
echo - 128KB per skriving
echo - Ny fil hvert 4. minut (hurtig test)
echo - Mixed streams: Cam, PGM, CLN filer
echo - Output: C:\temp_input (så File Agent kan kopiere dem)
echo.
echo Filnavne matcher template system:
echo - YYMMDD_HHMM_Ingest_Cam1.mxf  -> KAMERA folder
echo - YYMMDD_HHMM_Ingest_PGM.mxf   -> PROGRAM_CLEAN folder
echo - YYMMDD_HHMM_Ingest_CLN.mxf   -> PROGRAM_CLEAN folder
echo.

python file_growth_simulator.py ^
    --output-folder "C:\temp_input" ^
    --stream-count 6 ^
    --write-interval-ms 500 ^
    --chunk-size-kb 128 ^
    --clip-duration-minutes 4 ^
    --new-file-interval-minutes 0 ^
    --stream-mix mixed

pause