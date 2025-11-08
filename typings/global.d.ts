
interface UIHelpers {
    formatSizeFromGB(gb: number | null | undefined): string;
}

interface Window {
    UIHelpers: UIHelpers;
}
