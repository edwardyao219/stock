import {
  CandlestickData,
  CandlestickSeries,
  ColorType,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  LineData,
  LineSeries,
  Time,
  createChart,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { Candle, ParameterRecommendation } from "./api";

interface StrategyEvidenceChartProps {
  candles: Candle[];
  recommendation: ParameterRecommendation | null;
}

function lineData(candles: Candle[], key: "ma5" | "ma10" | "ma20" | "ma60"): LineData[] {
  return candles
    .filter((item) => item[key] !== null)
    .map((item) => ({ time: item.time as Time, value: item[key] as number }));
}

export function StrategyEvidenceChart({ candles, recommendation }: StrategyEvidenceChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const ma5Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma20Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma60Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const priceLineRef = useRef<IPriceLine | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#101418" },
        textColor: "#b8c0cc",
        fontFamily: "Inter, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: "#1f2933" },
        horzLines: { color: "#1f2933" },
      },
      rightPriceScale: {
        borderColor: "#29323d",
      },
      timeScale: {
        borderColor: "#29323d",
      },
    });
    candleSeriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: "#d84f4f",
      downColor: "#2fa36b",
      borderUpColor: "#d84f4f",
      borderDownColor: "#2fa36b",
      wickUpColor: "#d84f4f",
      wickDownColor: "#2fa36b",
    });
    ma5Ref.current = chart.addSeries(LineSeries, {
      color: "#f0b84f",
      lineWidth: 1,
      priceLineVisible: false,
    });
    ma20Ref.current = chart.addSeries(LineSeries, {
      color: "#4f8df0",
      lineWidth: 1,
      priceLineVisible: false,
    });
    ma60Ref.current = chart.addSeries(LineSeries, {
      color: "#a06ad8",
      lineWidth: 1,
      priceLineVisible: false,
    });
    chartRef.current = chart;

    return () => {
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      ma5Ref.current = null;
      ma20Ref.current = null;
      ma60Ref.current = null;
      priceLineRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    if (!chart || !candleSeries) return;

    candleSeries.setData(
      candles.map(
        (item): CandlestickData => ({
          time: item.time as Time,
          open: item.open,
          high: item.high,
          low: item.low,
          close: item.close,
        }),
      ),
    );
    ma5Ref.current?.setData(lineData(candles, "ma5"));
    ma20Ref.current?.setData(lineData(candles, "ma20"));
    ma60Ref.current?.setData(lineData(candles, "ma60"));

    if (priceLineRef.current) {
      candleSeries.removePriceLine(priceLineRef.current);
      priceLineRef.current = null;
    }

    const latest = candles.length ? candles[candles.length - 1] : null;
    if (latest && recommendation) {
      priceLineRef.current = candleSeries.createPriceLine({
        price: latest.close,
        color: "#e3e8ef",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: `${recommendation.rule_id ?? "规则"} 观察价`,
      });
    }

    chart.timeScale().fitContent();
  }, [candles, recommendation]);

  return (
    <div className="chart-wrap">
      <div ref={containerRef} className="chart-canvas" />
      {!candles.length ? (
        <div className="chart-empty">
          <span>暂无K线数据</span>
        </div>
      ) : null}
    </div>
  );
}
