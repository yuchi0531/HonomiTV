<template>
    <v-dialog content-class="capture-lightbox-dialog" max-width="980" transition="slide-y-transition"
        :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)">
        <div class="capture-lightbox" v-if="capture">
            <img class="capture-lightbox__image" :src="fullImageURL" :alt="capture.capture_metadata?.title ?? capture.filename">
            <a v-ripple class="capture-lightbox__download" :href="fullImageURL" :download="capture.filename">
                <Icon icon="fa6-solid:download" width="42px" />
            </a>
            <div class="capture-lightbox__info">
                <div class="capture-lightbox__metadata">
                    <span class="capture-lightbox__title" v-if="capture.capture_metadata">
                        {{ capture.capture_metadata.title }}
                    </span>
                    <span class="capture-lightbox__filename">{{ capture.filename }}</span>
                    <div class="capture-lightbox__details">
                        <span>{{ capture.image_width }}×{{ capture.image_height }}</span>
                        <span>{{ formattedFileSize }}</span>
                        <span>{{ formattedDate }}</span>
                        <span class="capture-lightbox__badge" v-if="capture.capture_metadata?.is_caption_composited">字幕あり</span>
                        <span class="capture-lightbox__badge" v-if="capture.capture_metadata?.is_comment_composited">コメントあり</span>
                    </div>
                    <div class="capture-lightbox__description" v-if="capture.capture_metadata?.description">
                        {{ capture.capture_metadata.description }}
                    </div>
                </div>
                <div class="capture-lightbox__actions">
                    <v-btn variant="flat" color="background-lighten-2" size="small" @click="$emit('addToFolder', capture)">
                        <Icon icon="fluent:folder-add-20-filled" width="18px" class="mr-1" />
                        フォルダに追加
                    </v-btn>
                    <v-btn class="capture-lightbox__delete" variant="flat" color="error" size="small"
                        :disabled="!canDelete" @click="$emit('delete', capture)">
                        <Icon icon="fluent:delete-20-regular" width="18px" class="mr-1" />
                        削除
                    </v-btn>
                </div>
            </div>
        </div>
    </v-dialog>
</template>
<script lang="ts" setup>

import { computed } from 'vue';

import Captures, { ICapture } from '@/services/Captures';
import { dayjs } from '@/utils';

const props = defineProps<{
    // ダイアログを表示するかどうか
    modelValue: boolean;
    // 拡大表示するキャプチャ (null の場合は何も表示しない)
    capture: ICapture | null;
    // 削除操作を許可するかどうか (管理者のみ許可される)
    canDelete: boolean;
}>();

defineEmits<{
    (e: 'update:modelValue', value: boolean): void;
    // フォルダへの追加が要求された
    (e: 'addToFolder', capture: ICapture): void;
    // 削除が要求された
    (e: 'delete', capture: ICapture): void;
}>();

// 原寸画像の URL
const fullImageURL = computed(() => props.capture ? Captures.getCaptureImageURL(props.capture.filename) : '');

// 撮影日時 (ファイルの更新日時を撮影日時の近似値として表示する)
const formattedDate = computed(() => props.capture ?
    dayjs(props.capture.file_modified_at).format('YYYY/MM/DD HH:mm:ss') : '');

// ファイルサイズを読みやすい単位に整形する
const formattedFileSize = computed(() => {
    const bytes = props.capture?.file_size ?? 0;
    if (bytes < 1024) {
        return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
});

</script>
<style lang="scss" scoped>

.capture-lightbox-dialog {
    margin: 12px;
}

.capture-lightbox {
    display: flex;
    position: relative;
    flex-direction: column;
    border-radius: 11px;
    background: rgb(var(--v-theme-background-lighten-1));
    overflow: hidden;

    &__image {
        display: block;
        width: 100%;
        max-height: 68vh;
        background: #000000;
        object-fit: contain;
    }

    &__download {
        display: flex;
        position: absolute;
        align-items: center;
        justify-content: center;
        right: 18px;
        bottom: 96px;
        width: 68px;
        height: 68px;
        border-radius: 50%;
        color: rgb(var(--v-theme-text));
        filter: drop-shadow(0 0 4.5px rgba(0, 0, 0, 90%));
        @include smartphone-vertical {
            right: 12px;
            bottom: 132px;
            width: 54px;
            height: 54px;
        }
    }

    &__info {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 12px 16px;
        @include smartphone-vertical {
            flex-direction: column;
            align-items: stretch;
        }
    }

    &__metadata {
        display: flex;
        flex: 1;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }

    &__title {
        overflow: hidden;
        font-size: 15px;
        font-weight: bold;
        white-space: nowrap;
        text-overflow: ellipsis;
    }

    &__filename {
        overflow: hidden;
        color: rgb(var(--v-theme-text-darken-1));
        font-size: 13px;
        white-space: nowrap;
        text-overflow: ellipsis;
    }

    &__details {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        color: rgb(var(--v-theme-text-darken-1));
        font-size: 12px;
    }

    &__description {
        display: -webkit-box;
        overflow: hidden;
        margin-top: 4px;
        color: rgb(var(--v-theme-text-darken-1));
        font-size: 12px;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
    }

    &__badge {
        padding: 1px 6px;
        border-radius: 4px;
        background: rgb(var(--v-theme-primary));
        color: #FFFFFF;
        font-size: 11px;
    }

    &__actions {
        display: flex;
        flex-shrink: 0;
        gap: 8px;
        @include smartphone-vertical {
            justify-content: flex-end;
        }
    }
}

</style>
<style lang="scss">

// スマホ横画面ではウインドウ幅いっぱいに広げる (既存のズームモーダルと同じ挙動)
@include smartphone-horizontal {
    .capture-lightbox-dialog {
        width: auto !important;
        max-width: none !important;
    }
}

</style>
