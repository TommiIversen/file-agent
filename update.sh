#!/bin/bash

# --- Konfiguration ---
# URL til GitHub repo'ets zip-fil (main-branchen)
REPO_URL="https://github.com/TommiIversen/file-agent/archive/refs/heads/main.zip"

# Navnet på zip-filen, der downloades
ZIP_FILE="file-agent-update.zip"

# GitHub laver en mappe inde i zip-filen, typisk "REPO-NAVN-BRANCH-NAVN"
# Sørg for at dette matcher (f.eks. main eller master)
EXTRACT_DIR="file-agent-main"
# ---------------------

echo "Starter opdatering af file-agent..."

# 1. Hent koden fra GitHub
echo "Downloader seneste version fra $REPO_URL..."
curl -L "$REPO_URL" -o "$ZIP_FILE"

# Tjek om download lykkedes
if [ $? -ne 0 ]; then
  echo "Fejl: Kunne ikke downloade opdatering. Afbryder."
  rm -f "$ZIP_FILE" # Slet den halvfærdige fil
  exit 1
fi

# 2. Pak koden ud
echo "Pakker opdatering ud..."
# '-o' flaget betyder "overwrite" (overskriv filer uden at spørge)
unzip -o "$ZIP_FILE"

# Tjek om den forventede mappe blev pakket ud
if [ ! -d "$EXTRACT_DIR" ]; then
    echo "Fejl: Kunne ikke finde den udpakkede mappe '$EXTRACT_DIR'."
    echo "Tjek om 'EXTRACT_DIR' variablen i scriptet er korrekt."
    rm "$ZIP_FILE"
    exit 1
fi

# 3. Erstat alle filer i nuværende mappe
# Vi bruger 'rsync' til at flytte alt INDE FRA $EXTRACT_DIR/
# til den nuværende mappe ('.')
echo "Erstatter filer i den nuværende mappe..."
rsync -a "$EXTRACT_DIR/" .

# 4. Ryd op
echo "Rydder op efter opdatering..."
rm "$ZIP_FILE"      # Slet zip-filen
rm -rf "$EXTRACT_DIR" # Slet den udpakkede mappe

echo "Opdatering fuldført!"
echo "Hvis dette script selv var en del af opdateringen, er det nu opdateret."