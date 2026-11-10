// One AG Grid theme for both grids, built with the Theming API from the app's own tokens
// (index.css): the same surfaces, borders, ink, accent and fonts as every card and button
// around the grids. Colours are CSS variables, so the theme follows dark mode by itself.

import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community"

// Community edition only. Nothing here needs an Enterprise license.
ModuleRegistry.registerModules([AllCommunityModule])

const SANS = ["Geist Variable", "ui-sans-serif", "system-ui", "sans-serif"]

export const calmTheme = themeQuartz.withParams({
  // type
  fontFamily: SANS,
  fontSize: 13,
  headerFontFamily: SANS,
  headerFontSize: 12,
  headerFontWeight: 500,

  // surfaces and ink
  backgroundColor: "var(--card)",
  foregroundColor: "var(--foreground)",
  borderColor: "var(--border)",
  headerBackgroundColor: "var(--card)",
  headerTextColor: "var(--muted-foreground)",
  headerCellHoverBackgroundColor: "var(--muted)",
  headerCellMovingBackgroundColor: "var(--muted)",
  rowHoverColor: "color-mix(in srgb, var(--muted) 70%, transparent)",
  selectedRowBackgroundColor: "var(--info-soft)",
  accentColor: "var(--primary)",
  modalOverlayBackgroundColor: "color-mix(in srgb, var(--card) 82%, transparent)",

  // rows held at the top (orders waiting for a human)
  pinnedRowBackgroundColor: "color-mix(in srgb, var(--warn-soft) 55%, var(--card))",
  pinnedRowBorder: { color: "var(--border)", width: 2 },

  // editing
  cellEditingBorder: { color: "var(--primary)", width: 2 },
  cellEditingShadow: "0 6px 20px color-mix(in srgb, var(--foreground) 14%, transparent)",
  inputBackgroundColor: "var(--card)",
  inputTextColor: "var(--foreground)",
  inputBorder: { color: "var(--border)" },
  inputFocusBorder: { color: "var(--primary)" },
  inputInvalidBorder: { color: "var(--bad)" },
  inputInvalidBackgroundColor: "var(--bad-soft)",
  inputBorderRadius: 8,
  pickerListBackgroundColor: "var(--card)",

  // checkboxes
  checkboxBorderRadius: 5,
  checkboxCheckedBackgroundColor: "var(--primary)",
  checkboxCheckedBorderColor: "var(--primary)",
  checkboxCheckedShapeColor: "var(--primary-foreground)",
  checkboxUncheckedBackgroundColor: "var(--card)",
  checkboxUncheckedBorderColor: "color-mix(in srgb, var(--muted-foreground) 55%, transparent)",

  // drag, resize, icons
  dragHandleColor: "var(--muted-foreground)",
  rowDragIndicatorColor: "var(--primary)",
  headerColumnResizeHandleColor: "var(--border)",
  iconButtonHoverBackgroundColor: "var(--muted)",

  // the flash is tinted per row in lib/gridFlash.ts, this is the fallback
  valueChangeValueHighlightBackgroundColor: "color-mix(in srgb, var(--primary) 22%, transparent)",

  // shape
  wrapperBorder: false,
  wrapperBorderRadius: 0,
  columnBorder: false,
  pinnedColumnBorder: { color: "var(--border)" },
  rowHeight: 44,
  headerHeight: 40,
  paginationPanelHeight: 44,
  cellHorizontalPadding: 14,
  spacing: 6,
})
