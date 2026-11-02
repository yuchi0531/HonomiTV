<template>
    <!-- ベース画面の中にそれぞれの設定画面で異なる部分を記述する -->
    <SettingsBase>
        <h2 class="settings__heading">
            <a v-ripple class="settings__back-button" @click="$router.back()">
                <Icon icon="fluent:chevron-left-12-filled" width="27px" />
            </a>
            <Icon icon="fluent:subtitles-16-filled" width="25px" />
            <span class="ml-3">字幕</span>
        </h2>
        <div class="settings__content">
            <div class="settings__item">
                <label class="settings__item-heading">字幕のフォント</label>
                <label class="settings__item-label">
                    プレイヤーで字幕表示をオンにしているときの、字幕のフォントを設定します。<br>
                </label>
                <v-select class="settings__item-form" color="primary" variant="outlined" hide-details
                    :density="is_form_dense ? 'compact' : 'default'"
                    :items="caption_font_options" v-model="caption_font_selection">
                </v-select>
                <!-- 一覧にないフォントを、OS に入っているフォント名で直接指定できるようにする -->
                <v-text-field class="settings__item-form mt-2" color="primary" variant="outlined" hide-details
                    :density="is_form_dense ? 'compact' : 'default'"
                    :disabled="caption_font_selection !== CUSTOM_FONT_VALUE"
                    placeholder="例: 源ノ角ゴシック JP"
                    hint="OS にインストールされているフォント名を入力します。ブラウザがそのフォントを使えない場合は、既定のフォントで表示されます。"
                    persistent-hint
                    v-model="settingsStore.settings.caption_font">
                </v-text-field>
            </div>
            <div class="settings__item settings__item--switch">
                <label class="settings__item-heading" for="always_border_caption_text">字幕の文字を常に縁取りする</label>
                <label class="settings__item-label" for="always_border_caption_text">
                    オンにすると、字幕の文字が縁取りされてより見やすくなります。とくに理由がなければ、オンにしておくのがおすすめです。<br>
                    オフのときも、字幕データから明示的に縁取りを指定されている場合には、オンのときと同様に字幕の文字が縁取りされます。<br>
                </label>
                <v-switch class="settings__item-switch" color="primary" id="always_border_caption_text" hide-details
                    v-model="settingsStore.settings.always_border_caption_text">
                </v-switch>
            </div>
            <div class="settings__item settings__item--switch">
                <label class="settings__item-heading" for="specify_caption_opacity">字幕の不透明度を指定する</label>
                <label class="settings__item-label" for="specify_caption_opacity">
                    オフのときは、字幕データから指定されている不透明度で描画します。<br>
                    とくに理由がなければ、オフにしておくのがおすすめです。<br>
                </label>
                <v-switch class="settings__item-switch" color="primary" id="specify_caption_opacity" hide-details
                    v-model="settingsStore.settings.specify_caption_opacity">
                </v-switch>
            </div>
            <div class="settings__item" :class="{'settings__item--disabled': settingsStore.settings.specify_caption_opacity === false}">
                <label class="settings__item-heading">字幕の不透明度</label>
                <label class="settings__item-label">
                    上の [字幕の不透明度を指定する] をオンに設定したときのみ有効です。不透明度を 0 に設定すれば、字幕の背景を非表示にできます。<br>
                </label>
                <div class="settings__item-label" ref="caption_opacity">
                    <v-slider class="settings__item-form" color="primary" show-ticks="always" thumb-label hide-details
                        :min="0" :max="1" :step="0.05" v-model="settingsStore.settings.caption_opacity"
                        :disabled="settingsStore.settings.specify_caption_opacity === false">
                    </v-slider>
                </div>
            </div>
            <v-divider class="mt-6"></v-divider>
            <div class="settings__item settings__item--switch">
                <label class="settings__item-heading" for="tv_show_superimpose">テレビをみるときに文字スーパーを表示する</label>
                <label class="settings__item-label" for="tv_show_superimpose">
                    文字スーパーは、緊急地震速報の赤テロップや、NHK BS のニュース速報のテロップなどで利用されています。とくに理由がなければ、オンにしておくのがおすすめです。<br>
                </label>
                <v-switch class="settings__item-switch" color="primary" id="tv_show_superimpose" hide-details
                    v-model="settingsStore.settings.tv_show_superimpose">
                </v-switch>
            </div>
            <div class="settings__item settings__item--switch">
                <label class="settings__item-heading" for="video_show_superimpose">ビデオをみるときに文字スーパーを表示する</label>
                <label class="settings__item-label" for="video_show_superimpose">
                    文字スーパーは、緊急地震速報の赤テロップや、NHK BS のニュース速報のテロップなどで利用されています。録画当時の文字スーパーによるニュース速報を確認したい方以外は、オフにしておくのがおすすめです。<br>
                </label>
                <v-switch class="settings__item-switch" color="primary" id="video_show_superimpose" hide-details
                    v-model="settingsStore.settings.video_show_superimpose">
                </v-switch>
            </div>
        </div>
    </SettingsBase>
</template>
<script lang="ts">

import { mapStores } from 'pinia';
import { defineComponent } from 'vue';

import useSettingsStore from '@/stores/SettingsStore';
import Utils from '@/utils';
import SettingsBase from '@/views/Settings/Base.vue';

export default defineComponent({
    name: 'Settings-Caption',
    components: {
        SettingsBase,
    },
    data() {
        return {

            // フォームを小さくするかどうか
            is_form_dense: Utils.isSmartphoneHorizontal(),

            // 任意のフォント名を入力する選択肢の値
            // 一覧にないフォントを使いたい場合に選ぶ
            CUSTOM_FONT_VALUE: '__custom__',

            // 字幕のフォントの選択肢
            caption_font: [
                {title: 'Windows TV ゴシック', value: 'Windows TV Gothic'},
                {title: 'Windows TV 丸ゴシック', value: 'Windows TV MaruGothic'},
                {title: 'Windows TV 太丸ゴシック', value: 'Windows TV FutoMaruGothic'},
                {title: 'ヒラギノTV丸ゴ', value: 'Hiragino TV Sans Rd S'},
                {title: '新丸ゴ ARIB', value: 'TT-ShinMGo-regular'},
                {title: 'Rounded M+ 1m for ARIB', value: 'Rounded M+ 1m for ARIB'},
                {title: 'BIZ UDゴシック', value: 'BIZ UDGothic'},
                {title: 'Noto Sans JP', value: 'Noto Sans JP'},
                {title: '游ゴシック', value: 'Yu Gothic'},
                {title: 'デフォルトのフォント', value: 'sans-serif'},
            ],
        };
    },
    computed: {
        ...mapStores(useSettingsStore),

        /**
         * フォントの選択肢 (一覧に任意入力を加えたもの)
         * @returns 選択肢の配列
         */
        caption_font_options(): Array<{title: string, value: string}> {
            return [
                ...this.caption_font,
                {title: '任意のフォント名を入力', value: this.CUSTOM_FONT_VALUE},
            ];
        },

        /**
         * フォントの選択状態
         * 一覧にあるフォントならその値、ない場合は任意入力の選択肢を選んだ状態にする
         */
        caption_font_selection: {
            get(): string {
                const current = this.settingsStore.settings.caption_font;
                // 一覧にあるフォントはそのまま選択状態にする
                if (this.caption_font.some((option) => option.value === current) === true) {
                    return current;
                }
                // 一覧にないフォント名が保存されている場合は、任意入力として扱う
                return this.CUSTOM_FONT_VALUE;
            },
            set(value: string): void {
                // 任意入力を選んだときは、現在の入力内容をそのまま残す
                if (value === this.CUSTOM_FONT_VALUE) {
                    return;
                }
                this.settingsStore.settings.caption_font = value;
            },
        },
    }
});

</script>