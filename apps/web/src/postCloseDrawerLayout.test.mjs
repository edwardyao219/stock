import { readFileSync } from "node:fs";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

const panelStart = app.indexOf('className="post-close-review-panel"');
const nextSection = app.indexOf('className="intraday-watch-strip"', panelStart);
const panelMarkup = app.slice(panelStart, nextSection);

assert(panelStart >= 0, "保留收盘复盘轻量入口");
assert(nextSection > panelStart, "能定位到收盘复盘入口的边界");
assert(app.includes("className={`post-close-review-drawer ${"), "收盘复盘重内容进入抽屉");
assert(styles.includes(".post-close-review-drawer"), "抽屉需要独立样式");
assert(!panelMarkup.includes("post-close-review-grid"), "复盘指标网格不能挤压主页面");
assert(!panelMarkup.includes("post-close-review-details"), "完整复盘文本不能挤压主页面");
assert(!panelMarkup.includes("after-close-push-status"), "6点推送明细不能挤压主页面");
assert(/body\s*\{[^}]*overflow:\s*auto/s.test(styles), "页面需要允许纵向滚动，避免工作区被顶部模块压扁");
assert(/\.app-shell\s*\{[^}]*height:\s*auto/s.test(styles), "桌面外壳不能固定 100vh 后隐藏主工作区");
assert(/\.workspace-layout\s*\{[^}]*min-height:\s*min\(520px,\s*calc\(100vh - 180px\)\)/s.test(styles), "股票工作区需要保留可用高度");
