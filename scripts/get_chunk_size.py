import asyncio
import aiofiles
import os
import time
import sys

# --- ⚠️ INDSTILLINGER DU SKAL ÆNDRE ---

# 1. Hvor meget data skal vi skrive i alt (f.eks. 1GB)
TOTAL_SIZE_TO_WRITE_MB = 100  # 1024 MB = 1GB
TOTAL_SIZE_TO_WRITE_BYTES = TOTAL_SIZE_TO_WRITE_MB * 1024 * 1024

# 2. Angiv stien til destinationen på dit NAS
#    Brug r'...' (raw string) for at sikre, at Windows UNC-stier virker.
#
#    Windows UNC Path Eksempel:
DESTINATION_FILE = r'\\skumhesten\testfeta\async_test.tmp'
#
#    macOS Mount Eksempel:
#DESTINATION_FILE = r'/Volumes/MitNAS/async_test.tmp'

# 3. Definer de chunk sizes (i bytes), du vil teste
CHUNK_SIZES_TO_TEST = [
    64 * 1024,          # 64KB
    256 * 1024,         # 256KB
    1 * 1024 * 1024,    # 1MB
    2 * 1024 * 1024,    # 2MB
    3 * 1024 * 1024,    # 3MB
    4 * 1024 * 1024,    # 4MB
    8 * 1024 * 1024,    # 8MB
    16 * 1024 * 1024,   # 16MB
    32 * 1024 * 1024,   # 32MB
    64 * 1024 * 1024,   # 64MB (Pas på RAM-forbrug)
]

# --- SLUT PÅ INDSTILLINGER ---


def get_human_readable_size(size_bytes):
    """Konverterer bytes til en læsevenlig streng (KB eller MB)"""
    if size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024}KB"
    else:
        return f"{size_bytes // 1024 // 1024}MB"

async def run_single_test(chunk_size, dest_file):
    """
    Kører en enkelt async test ved at generere data i RAM
    og skrive det til destinationsfilen.
    """
    chunk_str = get_human_readable_size(chunk_size)
    print(f"⏱️  Tester med chunk size: {chunk_str}...", end="", flush=True)

    # 1. Generer en datablok af tilfældige bytes i RAM
    try:
        data_chunk = os.urandom(chunk_size)
    except MemoryError:
        print(f" FEJL: Ikke nok RAM til at allokere en {chunk_str} chunk.")
        return (chunk_str, float('inf'), 0)
    except ValueError:
         print(f" FEJL: {chunk_str} er muligvis for stor til os.urandom().")
         return (chunk_str, float('inf'), 0)

    # 2. Start tidtagning og tællere
    start_time = time.perf_counter()
    total_bytes_written = 0

    try:
        # 3. Åbn filen asynkront og skriv til den i en løkke
        async with aiofiles.open(dest_file, 'wb') as f:
            while total_bytes_written < TOTAL_SIZE_TO_WRITE_BYTES:
                bytes_remaining = TOTAL_SIZE_TO_WRITE_BYTES - total_bytes_written
                
                # Sørg for, at vi ikke skriver mere end totalen
                if bytes_remaining >= chunk_size:
                    await f.write(data_chunk)
                    total_bytes_written += chunk_size
                else:
                    # Skriv den sidste, mindre del
                    await f.write(data_chunk[:bytes_remaining])
                    total_bytes_written += bytes_remaining
        
        # 4. Stop tid og beregn hastighed
        end_time = time.perf_counter()
        duration = end_time - start_time
        speed_mbps = TOTAL_SIZE_TO_WRITE_MB / duration
        
        print(f" Færdig! Tid: {duration:.2f} sek. (Hastighed: {speed_mbps:.2f} MB/s)")
        return (chunk_str, duration, speed_mbps)

    except Exception as e:
        print(f" FEJL under async write med {chunk_str}: {e}")
        return (chunk_str, float('inf'), 0)
    
    finally:
        # 5. Ryd op
        try:
            if os.path.exists(dest_file):
                os.remove(dest_file)
        except OSError as e:
            print(f"  ADVARSEL: Kunne ikke slette temp-fil: {e}")

async def main():
    # Tjek om destinationsmappen findes
    # os.path.dirname() og os.path.isdir() håndterer UNC-stier korrekt på Windows
    dest_dir = os.path.dirname(DESTINATION_FILE)
    
    if not dest_dir: # Hvis stien kun er et filnavn
        print(f"❌ FEJL: Angiv venligst en fuld sti til destinationen, inklusiv mappe.")
        sys.exit(1)
        
    if not os.path.isdir(dest_dir):
        print(f"❌ FEJL: Destinationsmappen '{dest_dir}' findes ikke eller er ikke tilgængelig.")
        print("Sørg for, at dit netværksshare er tilgængeligt, og stien er korrekt.")
        sys.exit(1)

    print("--- 🚀 Starter Async Kopi-Test (RAM -> NAS) ---")
    print(f"Total data:  {TOTAL_SIZE_TO_WRITE_MB} MB")
    print(f"Destination: {DESTINATION_FILE}")
    print("Sørg for at have 'aiofiles' installeret (`pip install aiofiles`)")
    print("-" * 30)

    results = []
    for size in CHUNK_SIZES_TO_TEST:
        # Vi kører hver test sekventielt for at undgå at de forstyrrer hinanden
        result = await run_single_test(size, DESTINATION_FILE)
        results.append(result)

    # --- Print Rapport ---
    print("\n" + "=" * 45)
    print(" 📊 RAPPORT: Async Write (RAM til NAS)")
    print(" (Sorteret efter hastighed - hurtigste først)")
    print("=" * 45)
    
    # Sorter resultater efter hastighed (kolonne 2), faldende
    sorted_results = sorted(results, key=lambda x: x[2], reverse=True)

    print(f"{'Chunk Size':<12} | {'Tid (sek)':<10} | {'Hastighed (MB/s)':<15}")
    print("-" * 45)
    
    for res in sorted_results:
        # res[0] = chunk_str, res[1] = duration, res[2] = speed_mbps
        if res[1] == float('inf'): # Håndter fejl
             print(f"{res[0]:<12} | {'FEJL':<10} | {'0.00':<15}")
        else:
            print(f"{res[0]:<12} | {res[1]:<10.2f} | {res[2]:<15.2f}")

    # Find den bedste
    if sorted_results and sorted_results[0][2] > 0:
        best = sorted_results[0]
        print("\n---")
        print(f"🏆 **Bedste valg: {best[0]}** (Hastighed: {best[2]:.2f} MB/s)")
    
    print("--- Test afsluttet ---")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest afbrudt af bruger.")
        # Sørg for at rydde op, hvis scriptet afbrydes
        try:
            if os.path.exists(DESTINATION_FILE):
                os.remove(DESTINATION_FILE)
                print("Midlertidig fil slettet.")
        except OSError:
            pass # Ignorer fejl ved oprydning