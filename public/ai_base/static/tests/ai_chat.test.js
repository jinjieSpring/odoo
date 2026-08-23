/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { click, queryAll, queryFirst, waitFor, waitForNone } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import {
    makeMockEnv,
    mockService,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";

import { AiChat } from "@ai_base/js/ai_chat";

defineMailModels();

const DEFAULTS = {
    model_ready: true,
    model_status: { code: "ready", title: "Model ready", message: "ok" },
    model_info: {
        capabilities: {
            streaming: true,
        },
    },
    attach_context: true,
    sidebar_collapsed: false,
    grid_sessions_collapsed: false,
    grid_knowledge_collapsed: false,
    grid_sessions_height: 0,
    grid_knowledge_height: 0,
    sidebar_width: 260,
    default_prompt_id: false,
    prompts: [],
    agents: [],
    default_agent_id: false,
};

const SESSION = {
    id: 1,
    name: "Session A",
    message_count: 4,
    write_date: "2026-08-18 04:00:00",
    input_tokens: 10,
    output_tokens: 5,
};

const SESSION_PAYLOAD = {
    messages: [
        { id: 1, role: "user", content: "first question" },
        { id: 2, role: "assistant", content: "first answer" },
        { id: 3, role: "user", content: "second question" },
        { id: 4, role: "assistant", content: "second answer" },
    ],
    session: {
        ...SESSION,
        context_usage: 12,
        capabilities: DEFAULTS.model_info.capabilities,
    },
};

let ormCalls;
let notifications;
let dialogs;

function makeOrm() {
    return {
        async call(model, method, args) {
            ormCalls.push([model, method, args]);
            if (method === "action_get_defaults") {
                return DEFAULTS;
            }
            if (method === "action_get_session") {
                return SESSION_PAYLOAD;
            }
            return {};
        },
        async searchRead() {
            return [SESSION];
        },
    };
}

async function mountChat() {
    await makeMockEnv();
    ormCalls = [];
    notifications = [];
    dialogs = [];
    mockService("orm", makeOrm());
    mockService("notification", () => ({
        add: (...args) => notifications.push(args),
    }));
    mockService("action", () => ({
        doAction: () => {},
        currentController: null,
    }));
    mockService("bus_service", () => ({
        subscribe: () => ({ unsubscribe: () => {} }),
    }));
    mockService("dialog", () => ({
        add: (...args) => dialogs.push(args),
    }));
    await mountWithCleanup(AiChat);
}

function typeInput(value) {
    const input = queryFirst(".o_ai_chat_input");
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
}

function keyOnInput(key) {
    const input = queryFirst(".o_ai_chat_input");
    input.focus();
    input.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true })
    );
}

test("user and assistant messages are rendered from the session", async () => {
    await mountChat();
    await waitFor(".o_ai_chat_msg.o_ai_user");
    expect(queryAll(".o_ai_chat_msg.o_ai_user")).toHaveCount(2);
    expect(queryAll(".o_ai_chat_msg.o_ai_assistant")).toHaveCount(2);
    expect(queryAll(".o_ai_chat_msg_content")[0].textContent).toInclude(
        "first question"
    );
});

test("status bar shows formatted usage", async () => {
    await mountChat();
    await waitFor(".o_ai_chat_status_tokens");
    expect(queryFirst(".o_ai_chat_status_tokens").textContent).toBe(
        "Input 10 \u00b7 Output 5 \u00b7 Context 12%"
    );
});

test("session row tooltip carries stats and update time", async () => {
    await mountChat();
    const title = queryFirst(".o_ai_session_item").getAttribute("title");
    expect(title).toInclude("4 messages");
    expect(title).toInclude("Input 10");
    expect(title).toInclude("Output 5");
    expect(title).toInclude("Updated");
});

test("empty input + ArrowUp browses user history", async () => {
    await mountChat();
    const input = queryFirst(".o_ai_chat_input");
    keyOnInput("ArrowUp");
    await animationFrame();
    expect(input.value).toBe("second question");
    keyOnInput("ArrowUp");
    await animationFrame();
    expect(input.value).toBe("first question");
    keyOnInput("ArrowDown");
    await animationFrame();
    expect(input.value).toBe("second question");
    // Any edit exits the browse mode.
    typeInput("second question!");
    await animationFrame();
    keyOnInput("ArrowUp");
    await animationFrame();
    expect(input.value).toBe("second question!");
});

test("slash command palette filters and Tab completes", async () => {
    await mountChat();
    typeInput("/");
    await animationFrame();
    await waitFor(".o_ai_chat_command");
    typeInput("/exp");
    await animationFrame();
    await waitFor(".o_ai_chat_command");
    expect(queryAll(".o_ai_chat_command")).toHaveCount(1);
    expect(queryFirst(".o_ai_chat_command").textContent).toInclude("/export");
    keyOnInput("Tab");
    await animationFrame();
    const input = queryFirst(".o_ai_chat_input");
    expect(input.value).toBe("/export ");
});

test("slash command /settings opens the user settings dialog", async () => {
    await mountChat();
    typeInput("/settings");
    keyOnInput("Enter");
    expect(dialogs.length).toBe(1);
});

test("editing a user message submits on plain Enter", async () => {
    await mountChat();
    await click(
        ".o_ai_chat_msg.o_ai_user .o_ai_chat_msg_actions button:has(.fa-pencil)"
    );
    await waitFor(".o_ai_chat_edit_msg textarea");
    const textarea = queryFirst(".o_ai_chat_edit_msg textarea");
    textarea.focus();
    textarea.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true })
    );
    await waitForNone(".o_ai_chat_edit_msg");
    expect(
        ormCalls.some(
            ([, method]) => method === "action_edit_and_resend"
        )
    ).toBe(true);
});

test("regenerate and resend call the expected model actions", async () => {
    await mountChat();
    await click(
        ".o_ai_chat_msg.o_ai_assistant .o_ai_chat_msg_actions button:has(.fa-rotate-right)"
    );
    await click(
        ".o_ai_chat_msg.o_ai_user .o_ai_chat_msg_actions button:has(.fa-rotate-left)"
    );
    expect(
        ormCalls.some(([, method]) => method === "action_regenerate")
    ).toBe(true);
    expect(
        ormCalls.some(([, method]) => method === "action_edit_and_resend")
    ).toBe(true);
});

test("agent picker stays hidden in systray chat", async () => {
    const previous = DEFAULTS.agents;
    const previousDefault = DEFAULTS.default_agent_id;
    DEFAULTS.agents = [
        { id: 1, name: "Assistant", run_mode: "chat" },
        { id: 7, name: "Closer", run_mode: "goal" },
    ];
    DEFAULTS.default_agent_id = 1;
    try {
        await mountChat();
        expect(".o_ai_status_agent").toHaveCount(0);
    } finally {
        DEFAULTS.agents = previous;
        DEFAULTS.default_agent_id = previousDefault;
    }
});
