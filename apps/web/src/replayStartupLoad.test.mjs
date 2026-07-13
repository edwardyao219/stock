import { readFileSync } from "node:fs";

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const mountEffectStart = app.indexOf("  useEffect(() => {\n    loadMarketOverview();");
const mountEffectEnd = app.indexOf("  }, []);", mountEffectStart);

if (mountEffectStart < 0 || mountEffectEnd < 0) {
  throw new Error("找不到应用启动加载逻辑");
}

const mountEffect = app.slice(mountEffectStart, mountEffectEnd);
if (mountEffect.includes("loadCandidateReplayEffect")) {
  throw new Error("应用启动时不能自动占用数据库执行候选长回放");
}
if (!app.includes("onClick={() => loadCandidateReplayEffect()}")) {
  throw new Error("策略效果仍需保留手动运行入口");
}
if (!app.includes("onClick={() => loadCandidateReplayEffect(longCandidateReplayQuery)}")) {
  throw new Error("长周期回放仍需保留手动运行入口");
}
