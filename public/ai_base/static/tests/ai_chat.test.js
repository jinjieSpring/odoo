/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { mockService, mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";

import { AiChat, readSse } from "@ai_base/js/ai_chat";

defineMailModels();

function sseBody(events) {
    return events
        .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
        .join("");
}

function mockReader(text) {
    const chunks = [new TextEncoder().encode(text)];
    return {
        async read() {
            if (!chunks.length) {
                return { done: true, value: undefined };
            }
            return { done: false, value: chunks.shift() };
        },
    };
}

function patchRpc(handlers) {
    patchWithCleanup(AiChat.prototype, {
        async rpc(route, params) {
            if (handlers[route]) {
                return handlers[route](params);
            }
            return {};
        },
    });
}

test("send streams assistant text", async () => {
    mockService("notification", { add() {} });
    patchRpc({
        "/ai_base/session/list": () => [{ id: 1, name: "Session A" }],
        "/ai_base/session/create": () => ({ id: 1 }),
        "/ai_base/session/get": () => ({
            session: { id: 1, name: "Session A" },
            messages: [],
        }),
    });
    patchWithCleanup(AiChat.prototype, {
        async _stream() {
            return {
                ok: true,
                body: {
                    getReader: () => mockReader(sseBody([
                        ["delta", { delta: "hello" }],
                        ["done", {}],
                    ])),
                },
            };
        },
    });
    const chat = await mountWithCleanup(AiChat, { props: { sessionId: 1 } });
    await animationFrame();
    chat.state.content = "hi";
    await chat.onSend();
    await animationFrame();
    expect(chat.state.messages.some(
        (msg) => msg.role === "assistant" && msg.content === "hello"
    )).toBe(true);
    expect(chat.state.error).toBe("");
});

test("stream error is shown", async () => {
    mockService("notification", { add() {} });
    patchRpc({
        "/ai_base/session/list": () => [],
        "/ai_base/session/create": () => ({ id: 2 }),
        "/ai_base/session/get": () => ({ session: { id: 2 }, messages: [] }),
    });
    patchWithCleanup(AiChat.prototype, {
        async _stream() {
            return {
                ok: true,
                body: {
                    getReader: () => mockReader(sseBody([
                        ["error", { error: "boom" }],
                        ["done", {}],
                    ])),
                },
            };
        },
    });
    const chat = await mountWithCleanup(AiChat, { props: { sessionId: 2 } });
    await animationFrame();
    chat.state.content = "hi";
    await chat.onSend();
    await animationFrame();
    expect(chat.state.error).toBe("boom");
});

test("readSse parses event frames", async () => {
    const events = [];
    const response = {
        body: {
            getReader: () => mockReader(sseBody([
                ["delta", { delta: "a" }],
                ["error", { error: "x" }],
            ])),
        },
    };
    await readSse(response, (event, data) => events.push([event, data]));
    expect(events).toEqual([
        ["delta", { delta: "a" }],
        ["error", { error: "x" }],
    ]);
});
