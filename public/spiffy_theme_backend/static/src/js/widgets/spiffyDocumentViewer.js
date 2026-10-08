/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { Component, onMounted, useExternalListener, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

const SCROLL_ZOOM_STEP = 0.1;
const ZOOM_STEP = 0.1;
const MIN_SCALE = 0.5;

export class spiffyDocumentViewer extends Component {
    static template = "spiffyDocumentViewer";
    static props = {
        attachments: Array,
        activeAttachmentID: Number,
    };

    /**
     * The documentViewer takes an array of objects describing attachments in
     * argument, and the ID of an active attachment (the one to display first).
     * Documents that are not of type image or video are filtered out.
     */
    setup() {
        this.state = useState({
            activeAttachment: null,
            scale: 1,
            angle: 0,
        });
        this.rootRef = useRef("autofocus");
        this.zoomerRef = useRef("zoomer");
        this.imgRef = useRef("viewerImg");
        this.modelName = "ir.attachment";
        this.enableDrag = false;
        this.dragStartX = 0;
        this.dragStartY = 0;
        this.dragstopX = 0;
        this.dragstopY = 0;

        this.attachment = this.props.attachments.filter((attachment) => {
            var match = attachment.type === 'url' ? attachment.url.match("(youtu|.png|.jpg|.gif)") : attachment.mimetype.match("(image|video|application/pdf|text)");
            if (match) {
                attachment.fileType = match[1];
                if (match[1].match("(.png|.jpg|.gif)")) {
                    attachment.fileType = 'image';
                }
                if (match[1] === 'youtu') {
                    var youtube_array = attachment.url.split('/');
                    var youtube_token = youtube_array[youtube_array.length - 1];
                    if (youtube_token.indexOf('watch') !== -1) {
                        youtube_token = youtube_token.split('v=')[1];
                        var amp = youtube_token.indexOf('&')
                        if (amp !== -1) {
                            youtube_token = youtube_token.substring(0, amp);
                        }
                    }
                    attachment.youtube = youtube_token;
                }
                return true;
            }
        });
        this.state.activeAttachment =
            this.attachment.find((attach) => attach.id === this.props.activeAttachmentID) || this.attachment[0];

        useExternalListener(document, "mousemove", this._onDrag);
        useExternalListener(document, "mouseup", this._onEndDrag);
        onMounted(() => {
            this.rootRef.el?.focus();
        });
    }

    get zoomIsDefault() {
        return Math.abs(this.state.scale - 1) < 1e-9;
    }

    get imageStyle() {
        const rotated = this.state.angle % 180 !== 0;
        const docHeight = Math.max(document.body?.scrollHeight || 0, document.documentElement.clientHeight);
        const docWidth = Math.max(document.body?.scrollWidth || 0, document.documentElement.clientWidth);
        const maxWidth = rotated ? `${docHeight}px` : "100%";
        const maxHeight = rotated ? `${docWidth}px` : "100%";
        return `transform: scale3d(${this.state.scale}, ${this.state.scale}, 1) rotate(${this.state.angle}deg); max-width: ${maxWidth}; max-height: ${maxHeight};`;
    }

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    _closeViewer() {
        registry.category("main_components").remove("spiffy_document");
    }

    _next() {
        // state.activeAttachment is a reactive proxy, so compare by id.
        var index = this.attachment.findIndex(item => item.id === this.state.activeAttachment?.id);
        index = (index + 1) % this.attachment.length;
        this.state.activeAttachment = this.attachment[index];
        this._reset();
    }

    _previous() {
        var index = this.attachment.findIndex(item => item.id === this.state.activeAttachment?.id);
        index = index <= 0 ? this.attachment.length - 1 : index - 1;
        this.state.activeAttachment = this.attachment[index];
        this._reset();
    }

    _reset() {
        this.state.scale = 1;
        this.dragStartX = this.dragstopX = 0;
        this.dragStartY = this.dragstopY = 0;
        if (this.zoomerRef.el) {
            this.zoomerRef.el.style.transform = "";
        }
    }

    /**
     * Rotate image clockwise by provided angle
     *
     * @private
     * @param {float} angle
     */
    _rotate(angle) {
        this._reset();
        this.state.angle = (this.state.angle || 0) + angle;
    }

    /**
     * Zoom in/out image by provided scale
     *
     * @private
     * @param {integer} scale
     */
    _zoom(scale) {
        if (scale > MIN_SCALE) {
            this.state.scale = scale;
        }
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    _onClose(e) {
        e.preventDefault();
        this._closeViewer();
    }

    _onDownload(e) {
        e.preventDefault();
        window.location = '/web/content/' + this.modelName + '/' + this.state.activeAttachment.id + '/' + 'datas' + '?download=true';
    }

    _onDrag(e) {
        if (!this.enableDrag) {
            return;
        }
        e.preventDefault();
        const image = this.imgRef.el;
        const zoomer = this.zoomerRef.el;
        if (!image || !zoomer) {
            return;
        }
        var top = image.offsetHeight * this.state.scale > zoomer.offsetHeight ? e.clientY - this.dragStartY : 0;
        var left = image.offsetWidth * this.state.scale > zoomer.offsetWidth ? e.clientX - this.dragStartX : 0;
        zoomer.style.transform = "translate3d(" + left + "px, " + top + "px, 0)";
        image.style.cursor = "move";
    }

    _onEndDrag(e) {
        if (!this.enableDrag) {
            return;
        }
        e.preventDefault();
        this.enableDrag = false;
        this.dragstopX = e.clientX - this.dragStartX;
        this.dragstopY = e.clientY - this.dragStartY;
        if (this.imgRef.el) {
            this.imgRef.el.style.cursor = "";
        }
    }

    /**
     * On click of image do not close modal so stop event propagation
     */
    _onImageClicked(e) {
        e.stopPropagation();
    }

    /**
     * Move next previous attachment on keyboard right left key
     */
    _onKeydown(e) {
        switch (e.key) {
            case "ArrowRight":
                this._next();
                break;
            case "ArrowLeft":
                this._previous();
                break;
            case "Escape":
                e.preventDefault();
                this._closeViewer();
                break;
            case "q":
                this._closeViewer();
                break;
        }
    }

    _onNext(e) {
        e.preventDefault();
        this._next();
    }

    _onPrevious(e) {
        e.preventDefault();
        this._previous();
    }

    _onPrint(e) {
        e.preventDefault();
        var src = this.imgRef.el?.getAttribute("src") || "";
        const printWindow = window.open("about:blank", "_new");
        printWindow.document.open();
        printWindow.document.write(`
                <html>
                    <head>
                        <script>
                            function onloadImage() {
                                setTimeout('printImage()', 10);
                            }
                            function printImage() {
                                window.print();
                                window.close();
                            }
                        </script>
                    </head>
                    <body onload='onloadImage()'>
                        <img src="${src}" alt=""/>
                    </body>
                </html>`);
        printWindow.document.close();
    }

    /**
     * Zoom image on scroll
     */
    _onScroll(e) {
        const scale = this.state.scale + (e.deltaY > 0 ? -SCROLL_ZOOM_STEP : SCROLL_ZOOM_STEP);
        this._zoom(scale);
    }

    _onStartDrag(e) {
        e.preventDefault();
        this.enableDrag = true;
        this.dragStartX = e.clientX - (this.dragstopX || 0);
        this.dragStartY = e.clientY - (this.dragstopY || 0);
    }

    /**
     * On click of video do not close modal so stop event propagation
     * and provide play/pause the video instead of quitting it
     */
    _onVideoClicked(e) {
        e.stopPropagation();
        var videoElement = e.target;
        if (videoElement.paused) {
            videoElement.play();
        } else {
            videoElement.pause();
        }
    }

    _onRotate(e) {
        e.preventDefault();
        this._rotate(90);
    }

    _onZoomIn(e) {
        e.preventDefault();
        this._zoom(this.state.scale + ZOOM_STEP);
    }

    _onZoomOut(e) {
        e.preventDefault();
        this._zoom(this.state.scale - ZOOM_STEP);
    }

    _onZoomReset(e) {
        e.preventDefault();
        if (this.zoomerRef.el) {
            this.zoomerRef.el.style.transform = "";
        }
        this._zoom(1);
    }
}
