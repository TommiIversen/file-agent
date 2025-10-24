## Directory Browser Modal Forbedringer

### ✅ Rettede problemer:

1. **Forbedrede ikoner:**
   - 📁 **Folders**: Blå folder ikon (uændret)
   - 🎬 **MXF/MXV filer**: Nyt gult video play-ikon (ingen spørgsmålstegn mere)
   - 📄 **Andre filer**: Grå dokument-ikon med linjer

2. **Reduceret spacing:**
   - Item rows: `p-3` → `p-1` (mindre padding mellem items)
   - Header: `p-3` → `p-2` (matchende header padding)

3. **Større modal:**
   - Bredde: `max-w-7xl` → `max-w-[90rem]` (ca. 20% bredere)
   - Højde: `max-h-[85vh]` (85% af viewport højde)

### 🎨 Ikoner detaljer:
- **Video filer (.mxf/.mxv)**: Video play ikon med viewBox="0 0 20 20"
- **Andre filer**: Dokument ikon med linjer (simulerer tekst)
- **Folders**: Uændret blå folder ikon

### 📐 Modal størrelse:
- **Før**: max-w-6xl (72rem = ~1152px)
- **Nu**: max-w-[90rem] (~1440px = ~25% større)
- **Højde**: 85% af browser vindues højde