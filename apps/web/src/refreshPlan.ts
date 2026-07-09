export type RefreshPageKey = "stocks" | "sectors";

export type AutoRefreshPlan = {
  workspace: boolean;
  marketOverview: boolean;
  intradayCandidates: boolean;
  sectorOverview: boolean;
  sectorCatalysts: boolean;
  dataHealth: boolean;
  candles: boolean;
};

export function buildAutoRefreshPlan(input: {
  activePage: RefreshPageKey;
  selectedSymbol: string | null;
  isDocumentVisible: boolean;
}): AutoRefreshPlan {
  if (!input.isDocumentVisible) {
    return {
      workspace: false,
      marketOverview: false,
      intradayCandidates: false,
      sectorOverview: false,
      sectorCatalysts: false,
      dataHealth: false,
      candles: false,
    };
  }
  const onSectorPage = input.activePage === "sectors";
  return {
    workspace: true,
    marketOverview: true,
    intradayCandidates: false,
    sectorOverview: onSectorPage,
    sectorCatalysts: onSectorPage,
    dataHealth: onSectorPage,
    candles: Boolean(input.selectedSymbol),
  };
}
