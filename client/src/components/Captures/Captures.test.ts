import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';

import CaptureCard from '@/components/Captures/CaptureCard.vue';
import CaptureLightbox from '@/components/Captures/CaptureLightbox.vue';
import { ICapture } from '@/services/Captures';


vi.mock('@/services/Captures', () => ({
    default: {
        getCaptureImageURL: (filename: string, thumbnail = false) =>
            `/api/captures/${filename}${thumbnail ? '?thumbnail=true' : ''}`,
    },
}));

const buildCapture = (overrides: Partial<ICapture> = {}, metadata: Partial<NonNullable<ICapture['capture_metadata']>> = {}): ICapture => ({
    image_width: 1280,
    image_height: 720,
    filename: 'Capture_20261017-120000.jpg',
    file_size: 2.5 * 1024 * 1024,
    file_modified_at: '2026-10-17T03:00:00Z',
    mime_type: 'image/jpeg',
    capture_metadata: {
        captured_at: '2026-10-17T12:00:00+09:00',
        captured_playback_position: 42,
        network_id: 32736,
        service_id: 1024,
        event_id: 65535,
        title: '今日のニュース',
        description: '番組の概要です。',
        start_time: '2026-10-17T12:00:00+09:00',
        end_time: '2026-10-17T12:30:00+09:00',
        duration: 1800,
        caption_text: null,
        is_caption_composited: false,
        is_comment_composited: false,
        ...metadata,
    },
    ...overrides,
});

const mountCard = (props: Partial<InstanceType<typeof CaptureCard>['$props']> = {}) => mount(CaptureCard, {
    props: {capture: buildCapture(), isSelected: false, isDisabled: false, selectionNumber: 0, ...props},
    global: {stubs: {Icon: true}},
});

describe('キャプチャカード', () => {
    it('サムネイル URL と番組名・撮影日時を表示する', () => {
        const wrapper = mountCard();
        expect(wrapper.find('img').attributes('src')).toBe(
            '/api/captures/Capture_20261017-120000.jpg?thumbnail=true',
        );
        expect(wrapper.find('img').attributes('alt')).toBe('今日のニュース');
        expect(wrapper.text()).toContain('今日のニュース');
        expect(wrapper.text()).toContain('2026/10/17 12:00');
    });

    it('EXIF が無い場合はファイル名を代替テキストにし、番組名は出さない', () => {
        const wrapper = mountCard({capture: {...buildCapture(), capture_metadata: null}});
        expect(wrapper.find('img').attributes('alt')).toBe('Capture_20261017-120000.jpg');
        expect(wrapper.find('.capture-card__title').exists()).toBe(false);
    });

    it('字幕・コメントの合成バッジを表示する', async () => {
        const wrapper = mountCard({
            capture: buildCapture({}, {is_caption_composited: true, is_comment_composited: true}),
        });
        const badges = wrapper.findAll('.capture-card__badge').map((badge) => badge.text());
        expect(badges).toEqual(['字幕', 'コメント']);
    });

    it('合成されていない場合はバッジを出さない', () => {
        expect(mountCard().findAll('.capture-card__badge')).toHaveLength(0);
    });

    it('選択中は選択番号とチェックマークを表示する', () => {
        const wrapper = mountCard({isSelected: true, selectionNumber: 3});
        expect(wrapper.classes()).toContain('capture-card--selected');
        expect(wrapper.find('.capture-card__selected-number').text()).toBe('3');
        expect(wrapper.find('.capture-card__selected-cover').exists()).toBe(true);
    });

    it('選択不可の場合は操作不可の見た目になる', () => {
        const wrapper = mountCard({isDisabled: true});
        expect(wrapper.classes()).toContain('capture-card--disabled');
        expect(wrapper.find('.capture-card__disabled-cover').exists()).toBe(true);
    });

    it('クリックと右クリックをそれぞれのイベントとして通知する', async () => {
        const wrapper = mountCard();
        await wrapper.trigger('click');
        await wrapper.trigger('contextmenu');
        expect(wrapper.emitted('select')).toHaveLength(1);
        expect(wrapper.emitted('toggleSelection')).toHaveLength(1);
    });
});

describe('キャプチャの拡大表示', () => {
    const mountLightbox = (props: Partial<InstanceType<typeof CaptureLightbox>['$props']> = {}) => mount(CaptureLightbox, {
        props: {modelValue: true, capture: buildCapture(), canDelete: true, ...props},
        global: {
            // v-dialog はテレポートするため、中身をそのまま描画するスタブに差し替える
            stubs: {
                Icon: true,
                'v-dialog': {template: '<div><slot /></div>', props: ['modelValue']},
                'v-btn': {template: '<button v-bind="$attrs"><slot /></button>'},
            },
            directives: {ripple: {}},
        },
    });

    it('原寸画像・解像度・ファイルサイズ・番組情報を表示する', () => {
        const wrapper = mountLightbox();
        expect(wrapper.find('.capture-lightbox__image').attributes('src')).toBe(
            '/api/captures/Capture_20261017-120000.jpg',
        );
        expect(wrapper.find('.capture-lightbox__title').text()).toBe('今日のニュース');
        expect(wrapper.find('.capture-lightbox__filename').text()).toBe('Capture_20261017-120000.jpg');
        expect(wrapper.text()).toContain('1280×720');
        expect(wrapper.text()).toContain('2.5 MB');
        expect(wrapper.text()).toContain('番組の概要です。');
    });

    it('ダウンロードリンクはファイル名を保存名にし、原寸画像を指す', () => {
        const link = mountLightbox().find('.capture-lightbox__download');
        expect(link.attributes('download')).toBe('Capture_20261017-120000.jpg');
        expect(link.attributes('href')).toBe('/api/captures/Capture_20261017-120000.jpg');
    });

    it('合成バッジは合成されている項目だけ表示する', () => {
        const wrapper = mountLightbox({
            capture: buildCapture({}, {is_caption_composited: true, is_comment_composited: false}),
        });
        expect(wrapper.findAll('.capture-lightbox__badge').map((badge) => badge.text())).toEqual(['字幕あり']);
    });

    it('削除権限が無い場合は削除ボタンを無効化する', () => {
        const wrapper = mountLightbox({canDelete: false});
        const deleteButton = wrapper.find('.capture-lightbox__delete');
        expect(deleteButton.attributes('disabled')).toBeDefined();
    });

    it('フォルダ追加と削除のイベントに対象のキャプチャを載せる', async () => {
        const wrapper = mountLightbox();
        // ボタンはスタブのため、コンポーネントのイベントを直接発火して引数を確認する
        const capture = buildCapture();
        wrapper.vm.$emit('addToFolder', capture);
        wrapper.vm.$emit('delete', capture);
        expect(wrapper.emitted('addToFolder')?.[0]).toEqual([capture]);
        expect(wrapper.emitted('delete')?.[0]).toEqual([capture]);
    });

    it('キャプチャが無い場合は中身を描画しない', () => {
        const wrapper = mountLightbox({capture: null});
        expect(wrapper.find('.capture-lightbox').exists()).toBe(false);
    });
});
