const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
const context = vm.createContext({
  document: { getElementById: () => null },
});
vm.runInContext(source.slice(0, source.indexOf("async function apiGet")), context);

const now = Date.parse("2026-09-27T08:05:00+08:00");
const row = {
  startTime: "2026-09-27T08:00:00+08:00",
  endTime: "2026-09-27T09:40:00+08:00",
  attendance: "已签到（待同步）",
};
assert.equal(context.signButtonMeta(row, now).canSign, false);
assert.equal(context.resolveCountdownText(row, now).state, "done");
assert.equal(context.attendanceMetaForRow(row, now).text, "已签到（待同步）");
assert.equal(context.signButtonMeta({ ...row, attendance: "未出勤" }, now).canSign, true);
assert.equal(context.signButtonMeta({ ...row, attendance: "正常出勤" }, now).canSign, false);
console.log("Web attendance display checks passed.");
