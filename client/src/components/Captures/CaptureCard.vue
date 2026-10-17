<template>
    <div class="capture-card" :class="{
            'capture-card--selected': isSelected,
            'capture-card--disabled': isDisabled,
        }"
        @click="$emit('select', capture)"
        @contextmenu.prevent="$emit('toggleSelection', capture)">
        <img class="capture-card__image" :src="thumbnailURL" :alt="capture.capture_metadata?.title ?? capture.filename"
            loading="lazy" decoding="async" draggable="false">
        <!-- 選択中はチェックマークと選択番号を重ねて表示する -->
        <div class="capture-card__selected-cover" v-if="isSelected">
            <span class="capture-card__selected-number">{{ selectionNumber }}</span>
        </div>
        <Icon class="capture-card__selected-checkmark" icon="fluent:checkmark-circle-16-filled" width="20px" />
        <div class="capture-card__disabled-cover"></div>
        <div class="capture-card__overlay">
            <span class="capture-card__title" v-if="capture.capture_metadata">
                {{ capture.capture_metadata.title }}
            </span>
            <span class="capture-card__date">{{ formattedDate }}</span>
        </div>
        <div class="capture-card__badges">
            <span class="capture-card__badge" v-if="capture.capture_metadata?.is_caption_composited">字幕</span>
            <span class="capture-card__badge" v-if="capture.capture_metadata?.is_comment_composited">コメント</span>
        </div>
    </div>
</template>
<script lang="ts" setup>

import { computed } from 'vue';

import Captures, { ICapture } from '@/services/Captures';
import { dayjs } from '@/utils';

const props = defineProps<{
    // 表示するキャプチャ
    capture: ICapture;
    // 選択済みかどうか
    isSelected: boolean;
    // 選択上限に達しているため選択不可かどうか
    isDisabled: boolean;
    // 選択中の並び順 (1始まり、未選択の場合は 0)
    selectionNumber: number;
}>();

defineEmits<{
    // カードがクリックされた (選択モードなら選択の切り替え、通常時は拡大表示)
    (e: 'select', capture: ICapture): void;
    // カードが右クリック・長押しされた (選択モードへの切り替えを兼ねる)
    (e: 'toggleSelection', capture: ICapture): void;
}>();

// 一覧用のサムネイル画像 URL
const thumbnailURL = computed(() => Captures.getCaptureImageURL(props.capture.filename, true));

// 撮影日時 (ファイルの更新日時を撮影日時の近似値として表示する)
const formattedDate = computed(() => dayjs(props.capture.file_modified_at).format('YYYY/MM/DD HH:mm'));

</script>
<style lang="scss" scoped>

.capture-card {
    position: relative;
    aspect-ratio: 16 / 9;
    border-radius: 8px;
    overflow: hidden;
    background: linear-gradient(150deg, rgb(var(--v-theme-gray)), rgb(var(--v-theme-background-lighten-2)));
    cursor: pointer;
    // content-visibility: auto は最終行のグリッドレイアウトを崩すことがあるため使用しない
    transition: opacity 0.15s;
    // 長押しで OS の画像メニューが出ないようにする (右クリック・長押しを選択モードに使うため)
    -webkit-touch-callout: none;
    user-select: none;

    &:hover {
        opacity: 0.85;
    }

    &__image {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    &__overlay {
        display: flex;
        position: absolute;
        flex-direction: column;
        gap: 1px;
        right: 0;
        bottom: 0;
        left: 0;
        padding: 20px 8px 6px;
        background: linear-gradient(transparent, rgba(0, 0, 0, 75%));
        pointer-events: none;
    }

    &__title {
        overflow: hidden;
        color: #FFFFFF;
        font-size: 12px;
        font-weight: bold;
        white-space: nowrap;
        text-overflow: ellipsis;
        @include smartphone-vertical {
            font-size: 11px;
        }
    }

    &__date {
        color: rgba(255, 255, 255, 80%);
        font-size: 11px;
        @include smartphone-vertical {
            font-size: 10px;
        }
    }

    &__badges {
        display: flex;
        position: absolute;
        gap: 3px;
        top: 4px;
        right: 4px;
        pointer-events: none;
    }

    &__badge {
        padding: 1px 5px;
        border-radius: 4px;
        background: rgba(0, 0, 0, 55%);
        color: #FFFFFF;
        font-size: 10px;
    }

    &__selected-cover {
        display: flex;
        position: absolute;
        align-items: center;
        justify-content: center;
        top: 0;
        right: 0;
        bottom: 0;
        left: 0;
        background: rgba(30, 19, 16, 45%);
    }

    &__selected-number {
        color: #FFFFFF;
        font-size: 34px;
        text-shadow: 0 0 2.5px rgba(0, 0, 0, 90%);
    }

    &__selected-checkmark {
        display: none;
        position: absolute;
        top: 5px;
        left: 6px;
        color: rgb(var(--v-theme-primary));
    }

    &__disabled-cover {
        display: none;
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        left: 0;
        background: rgba(30, 19, 16, 50%);
    }

    &--selected {
        outline: 3px solid rgb(var(--v-theme-primary));
        outline-offset: -3px;

        .capture-card__selected-checkmark {
            display: block;
        }
    }

    &--disabled {
        cursor: auto;

        .capture-card__disabled-cover {
            display: block;
        }
    }
}

</style>
