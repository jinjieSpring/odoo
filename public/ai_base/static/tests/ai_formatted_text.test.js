/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { queryAll, queryFirst, waitFor } from "@odoo/hoot-dom";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import {
    makeMockEnv,
    mockService,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";

import { AiFormattedText } from "@ai_base/js/ai_formatted_text";

defineMailModels();

async function mount(content) {
    await makeMockEnv();
    mockService("orm", () => ({
        call: async () => ({ type: "ir.actions.act_window" }),
    }));
    mockService("action", () => ({ doAction: () => {} }));
    mockService("notification", () => ({ add: () => {} }));
    await mountWithCleanup(AiFormattedText, { props: { content } });
}

test("renders headings, bold and inline code", async () => {
    await mount("# Title\n\n**bold** and `code`");
    await waitFor("h1");
    expect(queryFirst("h1").textContent).toInclude("Title");
    expect(queryAll("strong")).toHaveCount(1);
    expect(queryAll("code")).toHaveCount(1);
});

test("escapes raw HTML and never injects executable markup", async () => {
    await mount(
        '<script>alert(1)</script><b onclick="evil()">ok</b>' +
            "<img src=x onerror=alert(2)>"
    );
    await waitFor(".o_ai_formatted");
    expect(queryAll("script")).toHaveCount(0);
    expect(queryAll("[onclick]")).toHaveCount(0);
    expect(queryAll("[onerror]")).toHaveCount(0);
    expect(queryFirst(".o_ai_formatted").textContent).toInclude("ok");
});

test("renders a fenced code block with copy/download actions", async () => {
    await mount("```python\nprint(1)\n```");
    await waitFor("pre code");
    expect(queryAll(".o_ai_block_action")).toHaveCount(2);
});

test("renders knowledge citations as clickable superscripts", async () => {
    await mount("Answer with source [SOURCE:12].");
    await waitFor(".o_ai_citation");
    const citation = queryFirst(".o_ai_citation");
    expect(citation.textContent).toBe("[12]");
    expect(citation.dataset.chunkId).toBe("12");
});

test("falls back to plain code when mermaid rendering is unavailable", async () => {
    await mount("```mermaid\ngraph TD;A-->B;\n```");
    await waitFor(".o_ai_block_mermaid");
    await waitFor("pre code");
});
