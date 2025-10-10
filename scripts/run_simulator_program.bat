@echo off
REM File Growth Simulator - Template System Test (Program streams)

echo Starter File Growth Simulator - Program Streams...
echo.
echo Konfiguration:
echo - 4 program streams 
echo - Skriver hver 400ms
echo - 256KB per skriving
echo - Ny fil hvert 3. minut (hurtig test)
echo - Program filer: YYMMDD_HHMM_Ingest_PGM.mxf og YYMMDD_HHMM_Ingest_CLN.mxf
echo - Output: C:\temp_input
echo.
echo Alle filer går i PROGRAM_CLEAN folder med template system:
echo - Template rule: pattern:*PGM* folder:PROGRAM_CLEAN\{date}
echo - Template rule: pattern:*CLN* folder:PROGRAM_CLEAN\{date}
echo.

python file_growth_simulator.py ^
    --output-folder "C:\temp_input" ^
    --stream-count 4 ^
    --write-interval-ms 400 ^
    --chunk-size-kb 256 ^
    --clip-duration-minutes 3 ^
    --new-file-interval-minutes 0.5 ^
    --stream-mix program

pause