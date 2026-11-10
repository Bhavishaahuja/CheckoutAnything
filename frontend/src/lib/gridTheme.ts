import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community"

// Community edition only. Nothing here needs an Enterprise license.
ModuleRegistry.registerModules([AllCommunityModule])

// The grid reads the same CSS variables as the rest of the app, so it follows dark mode.
export const calmTheme = themeQuartz.withParams({
  fontFamily: "inherit",
  fontSize: 13,
  backgroundColor: "var(--card)",
  foregroundColor: "var(--foreground)",
  borderColor: "var(--border)",
  headerBackgroundColor: "var(--card)",
  headerTextColor: "var(--muted-foreground)",
  headerFontWeight: 500,
  headerFontSize: 12,
  rowHoverColor: "var(--muted)",
  selectedRowBackgroundColor: "var(--info-soft)",
  accentColor: "var(--primary)",
  // the wash on a cell whose value just changed (enableCellChangeFlash)
  valueChangeValueHighlightBackgroundColor: "color-mix(in srgb, var(--primary) 24%, transparent)",
  wrapperBorder: false,
  wrapperBorderRadius: 0,
  columnBorder: false,
  rowHeight: 44,
  headerHeight: 40,
  cellHorizontalPadding: 14,
  spacing: 6,
})
