@echo off
REM File Growth Simulator - Hurtig test version for udvikling

echo Starter File Growth Simulator (HURTIG TEST)...
echo.
echo Konfiguration:
echo - 3 video streams (reduceret for test)
echo - Skriver hver 100ms (hurtigere)
echo - 256KB per skriving (større chunks)
echo - Ny fil hvert 2. minut (hurtigere clipping)
echo - Streams starter alle samtidigt
echo - Output: C:\temp\sdi_recordings
echo.

python file_growth_simulator.py ^
    --output-folder "C:\temp\sdi_recordings" ^
    --stream-count 3 ^
    --write-interval-ms 100 ^
    --chunk-size-kb 256 ^
    --clip-duration-minutes 2 ^
    --new-file-interval-minutes 0

pause