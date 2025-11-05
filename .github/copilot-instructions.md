1. Vores Kernefilosofi (De Vigtigste Regler)
Vi følger en ren, domænedrevet arkitektur. Din primære opgave er at respektere og håndhæve denne struktur.

1. Domæne-først & SRP (Single Responsibility Principle)

Domæner er Loven: Al forretningslogik skal bo i et specifikt domæne (f.eks. app/domains/file_processing/).

Ingen "God Objects": En klasse skal have én grund til at ændre sig. FileRepository gemmer data. FileStateMachine validerer status. En CommandHandler udfører én handling.

Størrelsesgrænse: Vær proaktiv. Hvis en klasse (især en Handler) vokser over 150-200 linjer, skal du foreslå at opdele den.

2. Ensrettet Afhængighed (VIGTIGST!)

Core er Uafhængig: app/core/ (vores "motor" med EventBus, CQRS, FileStateMachine) må aldrig importere fra app/domains/.

Domæner er Uafhængige: app/domains/ må aldrig importere fra app/main.py eller app/domains/presentation/.

UI er Yderst: app/domains/presentation/ må gerne importere fra core og andre domæner (via CQRS), men intet må importere fra presentation.

2. Vores Arkitektur (Sådan er vi bygget)
Forstå denne struktur, før du skriver kode.

app/core/ (Motoren)
Dette er vores generiske infrastruktur. Den ved intet om "video" eller "kopiering".

file_repository.py: Den "dumme" data-adgang. Lige nu in-memory, men den skal behandles som en database (den er ved at blive til SQLite).

file_state_machine.py: Den eneste kilde til sandhed for hvordan filstatus må ændre sig.

events/: Hjemsted for DomainEventBus og alle event-definitioner (f.eks. FileReadyEvent).

cqrs/: Hjemsted for CommandBus og QueryBus.

app/domains/ (Hjernen / Forretningslogikken)
Dette er her, alt arbejde sker. Hver mappe er en "Vertical Slice".

file_discovery/: "Produceren". Finder filer og opretter dem.

file_processing/: "Consumeren". Håndterer alt relateret til kopiering, fejlhåndtering og jobkøen.

presentation/: Alt, der har med UI at gøre (API-endpoints, WebSockets, static/JS, templates).

storage/ & network_mount/: Specialiserede domæner, der håndterer hardware-overvågning og netværk.

shared/: Indeholder logik, der deles på tværs af domæner (f.eks. Config/Restart API'er).

3. De Nye Regler: Sådan Tilføjer du en Feature
Følg altid disse 4 regler, når du tilføjer ny kode.

Regel 1: Hvor skal koden bo?
Er det en ny forretnings-feature (f.eks. "check for virus")? -> Opret et nyt app/domains/virus_scan/ domæne.

Er det en del af en eksisterende feature (f.eks. "tilføj metadata til en fil")? -> Tilføj det til app/domains/file_discovery/.

Er det generisk infrastruktur (f.eks. en ny EmailService)? -> Tilføj det til app/core/.

Regel 2: CQRS-Først Princippet
Undgå at lave store "Service"-klasser. Brug CQRS.

Skal din feature ændre data eller udføre en handling?

Opret en Command i domæne/commands.py (f.eks. ScanFileForVirusCommand).

Opret en CommandHandler i domæne/command_handlers.py.

Registrer handleren i domæne/registration.py.

Kald den fra dit API/event handler via await command_bus.execute(...).

Skal din feature læse data?

Opret en Query i domæne/queries.py (f.eks. GetVirusScanResultQuery).

Opret en QueryHandler i domæne/query_handlers.py.

Registrer handleren.

Kald den fra dit API/event handler via await query_bus.execute(...).

Regel 3: State-ændringer SKAL bruge FileStateMachine
Dette er den vigtigste regel for at undgå fejl.

❌ GØR ALDRIG DETTE:

Python

# FORBUDT! Giver "anarkistisk" state.
tracked_file.status = FileStatus.FAILED
await self.file_repository.update(tracked_file)
✅ GØR ALTID DETTE:

Python

# KORREKT! Giver central validering og publicerer events.
try:
    await self.state_machine.transition(
        file_id=tracked_file.id, 
        new_status=FileStatus.FAILED,
        error_message="Virus scan failed"
    )
except InvalidTransitionError as e:
    logging.warning(f"Kunne ikke sætte status til FAILED: {e}")
Regel 4: Kommunikation MELLEM Domæner
Domæner må aldrig importere hinandens handlers eller services direkte.

Til ASYNKRON kommunikation (Løs kobling):

Brug: EventBus

Mønster: file_discovery publicerer FileReadyEvent. file_processing lytter efter den. file_discovery ved intet om file_processing.

Hvornår: "Jeg har gjort noget færdigt. Hvis andre er interesserede, kan de lytte."

Til SYNCHRON kommunikation (Medieret kobling):

Brug: QueryBus

Mønster: file_processing har brug for at vide, om netværket er oppe.

Korrekt: status = await self.query_bus.execute(GetNetworkStatusQuery()) (spørger bussen).

Forkert: from app.domains.network_mount.handlers import ... (direkte import).

Hvornår: "Jeg kan ikke fortsætte, før jeg får et svar fra et andet domæne."

4. Gamle "Code Smells"
Den gamle instruktionsfil indeholdt en lang liste af generiske "code smells". De er stadig gyldige, men vi stoler på, at du følger de 4 regler ovenfor, som er designet til at forhindre dem.