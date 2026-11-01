import { chromium } from "playwright";

const browser = await chromium.launch({headless: true});
const page = await browser.newPage({viewport: {width: 1440, height: 960}});
const errors = [];
page.on("pageerror", error => errors.push(String(error)));
page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });

await page.goto("http://127.0.0.1:8765", {waitUntil: "networkidle"});
await page.getByLabel("Matter name").fill("Moss v. Brightline");
await page.getByLabel("Docket number").fill("CV-2026-001");
await page.getByLabel("Plaintiff").fill("Jordan Moss");
await page.getByLabel("Defendant").fill("Brightline Delivery");
await page.getByLabel("Responding party").selectOption("plaintiff");
await page.getByLabel("Interrogating party").fill("Brightline Delivery");
await page.locator("#evidenceFiles").setInputFiles("/tmp/inquisitio_evidence.pdf");
await page.getByRole("button", {name: "Build response workspace"}).click();
await page.locator("#workspaceView").waitFor({state: "visible", timeout: 30000});
await page.getByRole("heading", {name: "Defendant's Interrogatories"}).waitFor();

const injury = page.locator('[data-item="202-2"]');
const injuryAnswer = await injury.locator("textarea").inputValue();
if (!injuryAnswer.includes("cervical strain")) {
  throw new Error("Supported injury evidence was not drafted automatically.");
}
await injury.getByRole("button", {name: "Review evidence"}).click();
await page.getByText("Jordan Moss sustained a cervical strain", {exact: false}).last().waitFor();
await page.locator(".evidence-panel").evaluate(panel => panel.classList.remove("open"));
await injury.locator("textarea").fill("The responding party sustained a cervical strain. Reviewed by counsel.");
await injury.getByRole("button", {name: "Revalidate edit"}).click();
await injury.getByRole("button", {name: "Approve"}).click();
await page.getByRole("button", {name: "Save responses"}).click();
await page.getByText("Responses saved.").waitFor();
await page.screenshot({path: "/tmp/inquisitio-desktop.png", fullPage: true});

const downloadPromise = page.waitForEvent("download");
await page.getByRole("button", {name: "Word"}).click();
const download = await downloadPromise;
await download.saveAs("/tmp/inquisitio-browser-export.docx");

const pdfDownloadPromise = page.waitForEvent("download");
await page.getByRole("button", {name: "Completed-form PDF"}).click();
const pdfDownload = await pdfDownloadPromise;
await pdfDownload.saveAs("/tmp/inquisitio-browser-form.pdf");

await page.setViewportSize({width: 390, height: 844});
await page.locator('[data-item="202-3"]').scrollIntoViewIfNeeded();
await page.locator('[data-item="202-3"]').getByRole("button", {name: "Review evidence"}).click();
await page.screenshot({path: "/tmp/inquisitio-mobile.png", fullPage: false});
await page.getByRole("button", {name: "Close evidence inspector"}).click();
const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
if (overflow) throw new Error("Mobile layout has horizontal overflow.");
if (errors.length) throw new Error(`Browser errors: ${errors.join(" | ")}`);

console.log(JSON.stringify({
  desktop: "/tmp/inquisitio-desktop.png",
  mobile: "/tmp/inquisitio-mobile.png",
  export: "/tmp/inquisitio-browser-export.docx",
  completedFormPdf: "/tmp/inquisitio-browser-form.pdf",
  supportedDraftAndApprovalVerified: true,
  mobileOverflow: false,
}, null, 2));
await browser.close();
