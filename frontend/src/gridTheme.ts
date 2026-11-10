import { themeQuartz } from 'ag-grid-community'

// one look for both grids, matched to the tokens in index.css
export const gridTheme = themeQuartz.withParams({
  fontFamily: 'inherit',
  fontSize: 14,
  backgroundColor: '#ffffff',
  foregroundColor: '#17211d',
  headerBackgroundColor: '#f3f5f2',
  headerTextColor: '#4b5852',
  headerFontWeight: 600,
  borderColor: '#dfe4df',
  rowHoverColor: '#f3f7f4',
  selectedRowBackgroundColor: '#e9f3ee',
  accentColor: '#1f6f54',
  wrapperBorderRadius: 6,
  rowHeight: 44,
  headerHeight: 40,
  spacing: 8,
})
