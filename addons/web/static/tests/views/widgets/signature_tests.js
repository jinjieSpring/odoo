/** @odoo-module **/
import { click, getFixture, patchWithCleanup, editInput, nextTick } from "@web/../tests/helpers/utils";
import { makeView, setupViewRegistries } from "@web/../tests/views/helpers";
import { patchUiSize } from "@mail/../tests/helpers/patch_ui_size";
import { NameAndSignature } from "@web/core/signature/name_and_signature";
import { SignatureWidget } from "@web/views/widgets/signature/signature";

let serverData;
let target;

QUnit.module("Widgets", (hooks) => {
    hooks.beforeEach(() => {
        target = getFixture();
        serverData = {
            models: {
                partner: {
                    fields: {
                        display_name: { string: "Name", type: "char" },
                        product_id: {
                            string: "Product Name",
                            type: "many2one",
                            relation: "product",
                        },
                        sign: { string: "Signature", type: "binary" },
                        signature: { string: "", type: "string" },
                    },
                    records: [
                        {
                            id: 1,
                            display_name: "Pop's Chock'lit",
                            product_id: 7,
                        },
                    ],
                    onchanges: {},
                },
                product: {
                    fields: {
                        name: { string: "Product Name", type: "char" },
                    },
                    records: [
                        {
                            id: 7,
                            display_name: "Veggie Burger",
                        },
                    ],
                },
            },
        };

        setupViewRegistries();
    });

    QUnit.module("Signature Widget");

    QUnit.test("Signature widget renders a Sign button", async function (assert) {
        assert.expect(5);

        patchWithCleanup(NameAndSignature.prototype, {
            setup() {
                this._super.apply(this, arguments);
                assert.strictEqual(this.props.signature.name, "");
            },
        });

        await makeView({
            type: "form",
            resModel: "partner",
            resId: 1,
            serverData,
            arch: `<form>
                    <header>
                        <widget name="signature" string="Sign"/>
                    </header>
                </form>`,
            mockRPC: async (route, args) => {
                if (route === "/web/sign/get_fonts/") {
                    return {};
                }
            },
        });

        assert.hasClass(
            target.querySelector("button.o_sign_button"),
            "btn-secondary",
            "The button must have the 'btn-secondary' class as \"highlight=0\""
        );
        assert.containsOnce(
            target,
            ".o_widget_signature button.o_sign_button",
            "Should have a signature widget button"
        );
        assert.containsNone(target, ".modal-dialog", "Should not have any modal");

        // Clicks on the sign button to open the sign modal.
        await click(target, ".o_widget_signature button.o_sign_button");
        assert.containsOnce(target, ".modal-dialog", "Should have one modal opened");
    });

    QUnit.test("Signature widget: full_name option", async function (assert) {
        patchWithCleanup(NameAndSignature.prototype, {
            setup() {
                this._super.apply(this, arguments);
                assert.step(this.props.signature.name);
            },
        });

        await makeView({
            type: "form",
            resModel: "partner",
            resId: 1,
            serverData,
            arch: `<form>
                        <header>
                            <widget name="signature" string="Sign" full_name="display_name"/>
                        </header>
                        <field name="display_name"/>
                    </form>`,
            mockRPC: async (route) => {
                if (route === "/web/sign/get_fonts/") {
                    return {};
                }
            },
        });
        // Clicks on the sign button to open the sign modal.
        await click(target, "span.o_sign_label");
        assert.containsOnce(target, ".modal .modal-body a.o_web_sign_auto_button");
        assert.verifySteps(["Pop's Chock'lit"]);
    });

    QUnit.test("Signature widget: highlight option", async function (assert) {
        await makeView({
            type: "form",
            resModel: "partner",
            resId: 1,
            serverData,
            arch: `<form>
                    <header>
                        <widget name="signature" string="Sign" highlight="1"/>
                    </header>
                </form>`,
            mockRPC: async (route, args) => {
                if (route === "/web/sign/get_fonts/") {
                    return {};
                }
            },
        });

        assert.hasClass(
            target.querySelector("button.o_sign_button"),
            "btn-primary",
            "The button must have the 'btn-primary' class as \"highlight=1\""
        );
        // Clicks on the sign button to open the sign modal.
        await click(target, ".o_widget_signature button.o_sign_button");
        assert.containsNone(target, ".modal .modal-body a.o_web_sign_auto_button");
    });

    QUnit.test("Signature widget works inside of a dropdown", async (assert) => {
        assert.expect(7);
        patchWithCleanup(SignatureWidget.prototype, {
            async onClickSignature() {
                await this._super.apply(this, arguments);
                assert.step("onClickSignature");
            },
            async uploadSignature({signatureImage}) {
                await this._super.apply(this, arguments);
                assert.step("uploadSignature");
            },
        });

        // force mobile view
        patchUiSize({ width: 225 });

        await makeView({
            type: "form",
            resModel: "partner",
            resId: 1,
            serverData,
            arch: `
                <form>
                    <header>
                        <button string="Dummy"/>
                        <widget name="signature" string="Sign" full_name="display_name"/>
                    </header>
                    <field name="display_name" />
                </form>
            `,
            mockRPC: async (route, args) => {
                if (route === "/web/sign/get_fonts/") {
                    return {};
                }
            },
        });

        // change display_name to enable auto-sign feature
        await editInput(target, ".o_field_widget[name=display_name] input", "test");

        // open the signature dialog
        await click(target, ".o_statusbar_buttons .dropdown-toggle");
        await click(target, ".o_widget_signature button.o_sign_button");

        assert.containsOnce(target, ".modal-dialog", "Should have one modal opened");

        // use auto-sign feature, might take a while
        await click(target, ".o_web_sign_auto_button");

        assert.containsOnce(target, ".modal-footer button.btn-primary");

        let maxDelay = 100;
        while (target.querySelector(".modal-footer button.btn-primary")["disabled"] && maxDelay > 0) {
            await nextTick();
            maxDelay--;
        }

        assert.equal(maxDelay > 0, true, "Timeout exceeded");

        // close the dialog and save the signature
        await click(target, ".modal-footer button.btn-primary:enabled");

        assert.containsNone(target, ".modal-dialog", "Should have no modal opened");

        assert.verifySteps(["onClickSignature", "uploadSignature"], "An error has occurred while signing");
    });
});
