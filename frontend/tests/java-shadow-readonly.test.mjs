import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("JavaShadowDataSource only issues GET requests to the operations API", async () => {
  const code = await source("src/dataSources.ts");
  const javaClass = code.slice(
    code.indexOf("export class JavaShadowDataSource"),
    code.indexOf("export function createDataSource")
  );

  assert.match(code, /\/internal\/xian\/node-matching\/operations/);
  assert.match(javaClass, /method: "GET"/);
  assert.doesNotMatch(javaClass, /method: "(?:POST|PUT|PATCH|DELETE)"/);
  for (const endpoint of ["/context", "/groups", "/recovery-groups", "/node-anomalies", "/payload-preview"]) {
    assert.ok(javaClass.includes(endpoint), `missing Java operations endpoint ${endpoint}`);
  }
  assert.match(javaClass, /node-anomalies\/export/);
  assert.match(javaClass, /report\.csv/);
  assert.match(javaClass, /statistics\.csv/);
});

test("URL state persists the required source, view and list context", async () => {
  const code = await source("src/urlState.ts");
  for (const name of ["source", "view", "groupId", "status", "query", "cursor", "stand", "min"]) {
    assert.ok(code.includes(`params.set("${name}"`), `URL parameter ${name} is not persisted`);
  }
  assert.match(code, /params\.append\("node"/);
  assert.match(code, /JAVA_SHADOW_VIEWS/);
});

test("Java anomaly requests use real offsets and send server filters", async () => {
  const code = await source("src/dataSources.ts");
  const params = code.slice(code.indexOf("function javaNodeAnomalyParams"), code.indexOf("function versionParams"));
  assert.match(params, /request\.cursor/);
  assert.match(params, /params\.set\("stand"/);
  assert.match(params, /params\.append\("eventNames"/);
  assert.match(params, /params\.set\("minCount"/);
  assert.match(params, /params\.set\("problemCode"/);
  assert.match(params, /params\.set\("query"/);
});

test("shared group workbenches load every Java page", async () => {
  const [code, dataSources] = await Promise.all([source("src/App.tsx"), source("src/dataSources.ts")]);
  const loader = code.slice(code.indexOf("async function loadEveryGroup"));
  assert.match(loader, /do \{/);
  assert.match(loader, /page\.next_cursor/);
  assert.match(loader, /items\.push\(\.\.\.page\.items\)/);
  assert.match(loader, /snapshotVersion/);
  assert.match(loader, /JavaShadowSnapshotChangedError/);
  assert.match(dataSources, /params\.set\("snapshotVersion"/);
});

test("guide-only anomalies use one synthetic node type in filters and statistics", async () => {
  const [dataSources, page, labels] = await Promise.all([
    source("src/dataSources.ts"),
    source("src/pages/NodeAnomalyCenter.tsx"),
    source("src/eventLabels.ts")
  ]);
  assert.match(dataSources, /anomalyType === "GUIDE_ONLY"/);
  assert.match(page, /item\.problem_code === "GUIDE_CAR_ONLY"/);
  assert.match(page, /nodeCounts\.set\("GUIDE_ONLY"/);
  assert.match(labels, /GUIDE_ONLY: "只有引导车节点"/);
});

test("anomaly stand statistics and filter options use the server-wide breakdown", async () => {
  const [dataSources, page, types] = await Promise.all([
    source("src/dataSources.ts"),
    source("src/pages/NodeAnomalyCenter.tsx"),
    source("src/types.ts")
  ]);
  assert.match(dataSources, /byStandAndNode = arrayValue\(statistics\.by_stand_and_node\)/);
  assert.match(dataSources, /by_stand_and_node: byStandAndNode/);
  assert.match(page, /report\?\.statistics\.by_stand_and_node\?\.length/);
  assert.match(page, /optionCatalog/);
  assert.match(page, /status: "ALL"/);
  assert.match(page, /eventNames: \[\]/);
  assert.match(page, /item\.occurrence_count/);
  assert.match(types, /by_stand_and_node\?: Array/);
});

test("recovery navigation rebuilds all loaded pages before restoring the selected row", async () => {
  const page = await source("src/pages/RecoveryQueue.tsx");
  assert.match(page, /loadRecoveryPages/);
  assert.match(page, /let pageCursor = "0"/);
  assert.match(page, /currentOffset >= targetOffset/);
  assert.match(page, /page\.items\.forEach\(\(item\) => byId\.set\(item\.group_id, item\)\)/);
  assert.match(page, /items: \[\.\.\.byId\.values\(\)\]/);
});

test("shared workbenches explicitly gate mutation controls in read-only mode", async () => {
  const [app, cluster, review, recovery, anomalies] = await Promise.all([
    source("src/App.tsx"),
    source("src/pages/ClusterReviewWorkbench.tsx"),
    source("src/pages/ReviewWorkbench.tsx"),
    source("src/pages/RecoveryQueue.tsx"),
    source("src/pages/NodeAnomalyCenter.tsx")
  ]);

  assert.match(app, /readOnly=\{dataSource\.readOnly\}/);
  assert.match(cluster, /readOnly \? "分组结论" : "聚类审核"/);
  assert.match(review, /Java影子判定/);
  assert.doesNotMatch(recovery, /from "\.\.\/api"/);
  assert.doesNotMatch(anomalies, /from "\.\.\/api"/);
});
