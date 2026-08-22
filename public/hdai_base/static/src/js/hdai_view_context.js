/** @odoo-module **/

import { useEffect } from "@odoo/owl";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { ListController } from "@web/views/list/list_controller";
import { session } from "@web/session";
import { patch } from "@web/core/utils/patch";

/**
 * Live record set of the list/kanban view currently displayed in the main
 * web client. The action service's ``currentController`` is only a metadata
 * object (action, props, state) and never exposes the mounted view model, so
 * the view controllers themselves publish their record set here through a
 * light patch. The chat dialog reads this store when it needs to display or
 * attach "n <model> records" context. List/kanban views have no meaningful
 * selection, so the whole record set of the current domain is tracked
 * (ids only; the backend does the counting and snapshot work).
 */
export const viewContext = {
    viewType: null,
    resModel: null,
    resIds: [],
    count: 0,
};

async function publishViewContext(viewType, controller) {
    try {
        const root = controller.model?.root;
        if (!root) {
            return;
        }
        let resIds = [];
        try {
            // All ids matching the current view domain (same limit as the
            // native "select all" actions); no record details are fetched.
            resIds = await controller.model.orm.search(
                root.resModel,
                root.domain || [],
                {
                    limit: session.active_ids_limit || 10000,
                    context: root.context || {},
                }
            );
        } catch (error) {
            resIds = root.records
                .map((record) => record.resId)
                .filter((rid) => Number.isInteger(rid) && rid > 0);
        }
        viewContext.viewType = viewType;
        viewContext.resModel = controller.props.resModel;
        viewContext.resIds = resIds.filter(
            (rid) => Number.isInteger(rid) && rid > 0
        );
        viewContext.count = Number(root.count) || viewContext.resIds.length;
    } catch (error) {
        console.error("hdai: failed to capture view records", error);
    }
}

function watchViewContext(viewType, controller) {
    useEffect(
        () => {
            publishViewContext(viewType, controller);
        },
        () => [
            controller.model?.root?.count,
            controller.model?.root?.selection?.length,
            controller.model?.root?.isDomainSelected,
        ]
    );
}

patch(ListController.prototype, {
    setup() {
        super.setup();
        watchViewContext("list", this);
    },
    async onSelectionChanged() {
        const result = await super.onSelectionChanged();
        await publishViewContext("list", this);
        return result;
    }
});

patch(KanbanController.prototype, {
    setup() {
        super.setup();
        watchViewContext("kanban", this);
    },
    async onSelectionChanged() {
        const result = await super.onSelectionChanged();
        await publishViewContext("kanban", this);
        return result;
    },
});
