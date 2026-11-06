// Immergas Dominus: loads the dashboard cards only when the IMMERGAS Modbus BMS NASA OpenTherm HUB cards are not already
// installed as a Lovelace resource - otherwise the (possibly older) copy bundled with the integration could define
// the elements first and shadow the newer hub cards. Served by the integration through frontend.add_extra_js_url.
const version = new URL(import.meta.url).searchParams.get("v") || "0";
const bundle = `/immergas_dominus/immergas-hub-cards.js?v=${version}`;

async function hubResourcePresent() {
  try {
    const { conn } = await window.hassConnection;
    const resources = await conn.sendMessagePromise({ type: "lovelace/resources" });
    return resources.some((r) => String(r.url).includes("immergas-hub-cards"));
  } catch (err) {
    // no connection yet or no right to list resources (non-admin user): load the bundled cards
    return false;
  }
}

if (customElements.get("immergas-now-card")) {
  console.info("Immergas Dominus: cards already loaded");
} else if (await hubResourcePresent()) {
  console.info("Immergas Dominus: using the cards from the hub resource");
} else {
  await import(bundle);
}
