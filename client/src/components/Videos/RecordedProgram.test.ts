import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import RecordedProgram from '@/components/Videos/RecordedProgram.vue';
import { IRecordedProgramDefault } from '@/services/Videos';
import useSettingsStore from '@/stores/SettingsStore';


vi.mock('@/components/Videos/RecordedProgramMenu.vue', () => ({default: {template: '<div />'}}));
vi.mock('vue-router', () => ({useRouter: () => ({push: vi.fn()})}));

// 一部のみ録画の録画番組を組み立てる
const buildProgram = () => ({
    ...IRecordedProgramDefault,
    id: 1,
    title: 'テスト番組',
    is_partially_recorded: true,
    recorded_video: {
        ...IRecordedProgramDefault.recorded_video,
        status: 'Recorded' as const,
        duration: 1700,
    },
});

describe('録画番組の「一部のみ録画」バッジ', () => {
    beforeEach(() => setActivePinia(createPinia()));

    it('設定がオンのときはバッジを表示する', () => {
        const settings = useSettingsStore();
        settings.settings.show_partially_recorded_badge = true;

        const wrapper = mount(RecordedProgram, {props: {program: buildProgram()}});

        expect(wrapper.text()).toContain('一部のみ録画');
        wrapper.unmount();
    });

    it('設定がオフのときはバッジを表示しない', () => {
        // 前後 CM をカットする運用では全番組が放送時間より短くなるため、バッジを消せるようにする
        const settings = useSettingsStore();
        settings.settings.show_partially_recorded_badge = false;

        const wrapper = mount(RecordedProgram, {props: {program: buildProgram()}});

        expect(wrapper.text()).not.toContain('一部のみ録画');
        wrapper.unmount();
    });

    it('一部のみ録画でない番組は設定に関係なくバッジを表示しない', () => {
        const settings = useSettingsStore();
        settings.settings.show_partially_recorded_badge = true;

        const wrapper = mount(RecordedProgram, {
            props: {program: {...buildProgram(), is_partially_recorded: false}},
        });

        expect(wrapper.text()).not.toContain('一部のみ録画');
        wrapper.unmount();
    });
});
