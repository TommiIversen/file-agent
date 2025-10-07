@echo off
REM File Growth Simulator - Hurtig test konfiguration

echo Starter File Growth Simulator...
echo.
echo Konfiguration:
echo - 8 video streams
echo - Skriver hver 500ms
echo - 64KB per skriving (~128KB/s per stream)
echo - Ny fil hvert 60. minut
echo - Streams starter alle samtidigt
echo - Output: C:\temp\sdi_recordings
echo.

python file_growth_simulator.py ^
    --output-folder "C:\temp\sdi_recordings" ^
    --stream-count 8 ^
    --write-interval-ms 500 ^
    --chunk-size-kb 64 ^
    --clip-duration-minutes 60 ^
    --new-file-interval-minutes 0

pause