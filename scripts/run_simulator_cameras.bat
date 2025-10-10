@echo off
REM File Growth Simulator - Template System Test (Kamera streams)

echo Starter File Growth Simulator - Kun Kamera Streams...
echo.
echo Konfiguration:
echo - 4 kamera streams
echo - Skriver hver 300ms (hurtigere test)
echo - 256KB per skriving
echo - Ny fil hvert 3. minut (hurtig test)
echo - Kun kamera filer: YYMMDD_HHMM_Ingest_Cam1.mxf etc.
echo - Output: C:\temp_input
echo.
echo Alle filer går i KAMERA folder med template system:
echo - Template rule: pattern:*Cam* folder:KAMERA\{date}
echo.

python file_growth_simulator.py ^
    --output-folder "C:\temp_input" ^
    --stream-count 4 ^
    --write-interval-ms 300 ^
    --chunk-size-kb 256 ^
    --clip-duration-minutes 3 ^
    --new-file-interval-minutes 0.5 ^
    --stream-mix cameras

pause