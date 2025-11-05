import time
from busylight.lights.kuando import Busylight

try:
    # Find og initialisér din Busylight
    # Hvis du kun har én, vil first_light() finde den.
    light = Busylight.first_light()

    if not light:
        print("Kunne ikke finde en Kuando Busylight.")
        exit()

    print("Fandt Busylight! Tænder rødt lys i 5 sekunder...")
    # Tænd med en RGB-farve (Rød, Grøn, Blå)
    # (255, 0, 0) er rød
    light.on((255, 0, 0))

    time.sleep(5) # Venter i 5 sekunder

    print("Skifter til grønt lys i 5 sekunder...")
    # (0, 255, 0) er grøn
    light.on((0, 255, 0))

    time.sleep(5) # Venter i 5 sekunder

except Exception as e:
    print(f"Der opstod en fejl: {e}")

finally:
    # Sørg for at slukke lyset, uanset hvad
    print("Slukker lyset.")
    try:
        # For at slukke, sætter vi farven til (0, 0, 0)
        light.on((0, 0, 0)) 
    except:
        pass # Lyset blev måske aldrig fundet