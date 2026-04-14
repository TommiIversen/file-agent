1. Kernefilosofi & Mentalitet
Vi følger en ren, domænedrevet arkitektur. Din primære opgave er at respektere denne struktur og følge "Karpathy-metoden" for implementering.

Karpathy-Principper (Adfærd)
Tænk før du koder: Lav aldrig antagelser. Hvis en opgave er tvetydig, skal du spørge om afklaring, før du skriver kode. Præsenter trade-offs, hvis der er flere løsninger.

Simplicitet først: Skriv kun den nødvendige kode. Ingen "speculative features" eller overflødig "fleksibilitet". Hvis 200 linjer kan blive til 50, så vælg 50.

Kirurgiske ændringer: Rør kun ved det, du absolut skal. Undgå at "rydde op" i tilstødende filer eller ændre formatering, medmindre du bliver bedt om det. Match eksisterende stil 100%.

Arkitektoniske Love
Domæner er Loven: Al forretningslogik skal bo i et specifikt domæne (f.eks. app/domains/file_processing/).

SRP (Single Responsibility Principle): En klasse skal have én grund til at ændre sig. FileRepository gemmer data. FileStateMachine validerer status. En CommandHandler udfører én handling.

Størrelsesgrænse: Vær proaktiv. Hvis en klasse (især en Handler) vokser over 2-300 linjer, skal du foreslå at opdele den.

Ensrettet Afhængighed (VIGTIGST): * app/core/ må aldrig importere fra app/domains/.

app/domains/ må aldrig importere fra app/main.py eller app/domains/presentation/.

app/domains/presentation/ må importere fra core og domæner (via CQRS), men intet må importere fra presentation.

2. Arkitektur (Struktur)
Forstå denne struktur i dybden, før du skriver eller flytter kode:

app/core/ (Motoren): Generisk infrastruktur. Den ved intet om "video" eller "kopiering".

file_repository.py: Data-adgang (behandles som en database/SQLite).

file_state_machine.py: Den eneste kilde til sandhed for status-ændringer.

events/: Hjemsted for DomainEventBus og event-definitioner (f.eks. FileReadyEvent).

cqrs/: Hjemsted for CommandBus og QueryBus.

app/domains/ (Hjernen): Hver mappe er en "Vertical Slice".

file_discovery/: "Produceren". Finder filer og opretter dem.

file_processing/: "Consumeren". Håndterer kopiering, fejl og jobkø.

presentation/: UI, API-endpoints, WebSockets, JS, templates.

storage/ & network_mount/: Hardware-overvågning og netværk.

shared/: Logik delt på tværs (f.eks. Config/Restart API'er).

3. Regler for Tilføjelse af Features
Følg altid disse 4 regler ved ny kode:

Regel 1: Placering
Ny forretnings-feature (f.eks. "virus scan")? -> Nyt domæne i app/domains/virus_scan/.

Del af eksisterende feature (f.eks. "metadata")? -> Tilføj til app/domains/file_discovery/.

Generisk infrastruktur (f.eks. EmailService)? -> Tilføj til app/core/.

Regel 2: CQRS-Først Princippet
Undgå store services. Brug bussen:

Commands (Handlinger): Opret Command og Handler i domænet. Registrer i registration.py. Kald via await command_bus.execute(...).

Queries (Læsning): Opret Query og Handler i domænet. Registrer og kald via await query_bus.execute(...).

Regel 3: State-ændringer SKAL bruge FileStateMachine
FORBUDT: tracked_file.status = FileStatus.FAILED.
KORREKT: ```python
await self.state_machine.transition(
file_id=tracked_file.id,
new_status=FileStatus.FAILED,
error_message="Virus scan failed"
)


### Regel 4: Kommunikation MELLEM Domæner
Ingen direkte imports af handlere/services på tværs.
* **Asynkron:** Brug `EventBus` (file_discovery publicerer, andre lytter).
* **Synkron:** Brug `QueryBus` (f.eks. `GetNetworkStatusQuery()`).

---

## 4. Kvalitet & Mål-drevet Eksekvering
Vi bruger en "Goal-Driven" tilgang. Du er ikke færdig, før succeskriterierne er mødt og verificeret.

### Quality Gate (ALLE skal bestå)
Al kode SKAL bestå uden snyd (`# type: ignore` eller `# noqa` er forbudt):
```bash
pytest --ignore=scripts      # Alle tests skal være grønne
mypy app/                    # Ingen type-fejl
lint-imports                 # Arkitektur-kontrakter skal holde
Hvis en ændring bryder et af disse tjek, SKAL det fikses i samme ændring.

5. Vedligeholdelse & Code Smells
Ryd op efter dine egne ændringer: Fjern imports/variabler, som DINE ændringer har gjort overflødige.

Surgical Principle: Fjern ikke pre-eksisterende dead code eller nabo-kode, medmindre du specifikt bliver bedt om det.

Dokumentation: Respekter eksisterende kommentarer. Hvis du ændrer logikken fundamentalt, skal dokumentationen følge med.