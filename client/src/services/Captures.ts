
import { AxiosError } from 'axios';

import Message from '@/message';
import APIClient from '@/services/APIClient';
import Utils, { Semaphore } from '@/utils';


/** キャプチャ画像の EXIF XPComment に格納されたメタデータ (サーバー側の CaptureMetadata に対応) */
export interface ICaptureMetadata {
    // キャプチャの撮影時刻 (ISO8601 フォーマット)
    captured_at: string;
    // 番組開始時刻から換算したキャプチャ位置 (秒)
    captured_playback_position: number;
    // チャンネルの network_id (放送波の識別子を持たないキャプチャでは null)
    network_id: number | null;
    // チャンネルの service_id
    service_id: number | null;
    // 番組の event_id
    event_id: number | null;
    // 番組名
    title: string;
    // 番組概要
    description: string;
    // 番組開始時刻 (ISO8601 フォーマット)
    start_time: string;
    // 番組終了時刻 (ISO8601 フォーマット)
    end_time: string;
    // 番組長 (秒)
    duration: number;
    // 字幕のテキスト (キャプチャした瞬間に字幕が表示されていなかった場合は null)
    caption_text: string | null;
    // キャプチャに字幕が合成されているかどうか
    is_caption_composited: boolean;
    // キャプチャにコメントが合成されているかどうか
    is_comment_composited: boolean;
}

/** キャプチャ画像の情報を表すインターフェイス (サーバー側の Capture に対応) */
export interface ICapture {
    // 画像の幅・高さは一覧で真っ先に確認したい情報なので、定義の先頭にまとめる
    image_width: number;
    image_height: number;
    // ファイル名 (拡張子を含む) / ファイルサイズ (バイト)
    filename: string;
    file_size: number;
    // ファイルの最終更新日時 (キャプチャ撮影日時の近似値)
    file_modified_at: string;
    // MIME タイプ
    mime_type: 'image/jpeg' | 'image/png';
    // EXIF XPComment から抽出したメタデータ (EXIF が無い・壊れている場合は null)
    capture_metadata: ICaptureMetadata | null;
}

/** キャプチャ一覧のレスポンスを表すインターフェイス (サーバー側の Captures に対応) */
export interface ICaptures {
    // 条件に一致するキャプチャの総数 (ページネーション適用前)
    total: number;
    // 現在のページのキャプチャのリスト
    captures: ICapture[];
}

/** キャプチャフォルダ情報を表すインターフェイス (サーバー側の CaptureFolder に対応) */
export interface ICaptureFolder {
    // フォルダ ID / フォルダ名 / 表示順序
    id: number;
    name: string;
    sort_order: number;
    // フォルダに登録されているキャプチャの件数 (実ファイルが消えているものも含む登録件数)
    capture_count: number;
    // 作成日時・更新日時
    created_at: string;
    updated_at: string;
}

/** キャプチャフォルダ一覧のレスポンスを表すインターフェイス (サーバー側の CaptureFolders に対応) */
export interface ICaptureFolders {
    total: number;
    folders: ICaptureFolder[];
}


class Captures {

    // 同時アップロード数の上限 & セマフォインスタンス
    private static readonly MAX_CONCURRENT_UPLOADS = 5;
    private static readonly semaphore = new Semaphore(Captures.MAX_CONCURRENT_UPLOADS);

    /**
     * キャプチャをサーバーにアップロードし保存する
     * @param blob キャプチャ画像の Blob
     * @param filename サーバーに保存するときのファイル名
     */
    static async uploadCapture(blob: Blob, filename: string): Promise<void> {

        // リトライループ
        // 成功するか、リトライ不可なエラーが発生するまで継続
        // eslint-disable-next-line no-constant-condition
        while (true) {

            // キャプチャ画像の File オブジェクト (= Blob) を FormData に入れる
            // multipart/form-data で送るために必要
            // ref: https://r17n.page/2020/02/04/nodejs-axios-file-upload-api/
            const form_data = new FormData();
            form_data.append('image', blob, filename);

            // セマフォを取得し、アップロードを同時 5 件までに制限する
            await this.semaphore.acquire();
            let response: Awaited<ReturnType<typeof APIClient.post>>;
            try {
                // API リクエストを実行
                response = await APIClient.post('/captures', form_data, {
                    headers: {'Content-Type': 'multipart/form-data'},
                    // 回線状況によってはアップロードに時間がかかることがあるので、
                    // タイムアウトを 60 秒に伸ばす
                    timeout: 60 * 1000,
                });
            } finally {
                // セマフォを必ず解放する (アップロード試行 1 回分のみを占有)
                this.semaphore.release();
            }

            // 成功
            if (response.type !== 'error') {
                return;
            }

            // エラー処理
            switch (response.data.detail) {
                case 'Permission denied to save the file': {
                    Message.error('キャプチャのアップロードに失敗しました。保存先フォルダに書き込み権限がありません。');
                    return;
                }
                case 'No space left on the device': {
                    Message.error('キャプチャのアップロードに失敗しました。保存先フォルダに空き容量がありません。');
                    return;
                }
                case 'Unexpected error occurred while saving the file': {
                    Message.error('キャプチャのアップロードに失敗しました。保存中に予期しないエラーが発生しました。');
                    return;
                }
                default: {
                    if (Number.isNaN(response.status)) {
                        // HTTP リクエスト自体が失敗した場合はネットワークエラーの可能性が高い & 基本アップロードに失敗してはならないので、リトライする
                        // リトライする前に 1 ~ 15 秒程度ランダムに待機することで、
                        // リトライリクエストが同じタイミングで殺到するのを回避する
                        const sleep_time_seconds = 1 + Math.random() * 15;
                        if (response.error.code === AxiosError.ECONNABORTED) {
                            // ネットワーク接続エラーの場合
                            Message.warning(`キャプチャのアップロード中にサーバーへの接続が切断されました。${sleep_time_seconds.toFixed(2)} 秒後にリトライします。`);
                        } else if (response.error.code === AxiosError.ETIMEDOUT) {
                            // タイムアウトの場合
                            Message.warning(`キャプチャのアップロード中にサーバーへの接続がタイムアウトしました。${sleep_time_seconds.toFixed(2)} 秒後にリトライします。`);
                        } else if (response.error.code === AxiosError.ERR_NETWORK) {
                            // 予期しないネットワークエラーの場合
                            Message.warning(`キャプチャのアップロード中に予期しないネットワークエラーが発生しました。${sleep_time_seconds.toFixed(2)} 秒後にリトライします。`);
                        } else {
                            // それ以外のエラーの場合
                            Message.warning(`キャプチャのアップロードに失敗しました。${sleep_time_seconds.toFixed(2)} 秒後にリトライします。`);
                        }
                        await Utils.sleep(sleep_time_seconds);  // 秒単位で指定
                        // ループ先頭に戻ってリトライ
                        continue;
                    } else {
                        APIClient.showGenericError(response, 'キャプチャのアップロードに失敗しました。');
                        return;
                    }
                }
            }
        }
    }

    /**
     * キャプチャ一覧を取得する
     * @param order ソート順序 ('desc': 新しい順, 'asc': 古い順)
     * @param page ページ番号 (1始まり)
     * @param search ファイル名・番組名・チャンネル名での部分一致検索キーワード (省略時は全件)
     * @returns キャプチャ一覧 (取得に失敗した場合は null)
     */
    static async fetchCaptures(
        order: 'desc' | 'asc' = 'desc',
        page: number = 1,
        search?: string,
    ): Promise<ICaptures | null> {
        // undefined のパラメータは axios が自動的に除外するため、そのまま渡して良い
        const response = await APIClient.get<ICaptures>('/captures', {
            params: {order, page, search},
        });
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'キャプチャ一覧の取得に失敗しました。');
            return null;
        }
        return response.data;
    }

    /**
     * キャプチャ画像の URL を生成する
     * @param filename キャプチャ画像のファイル名
     * @param thumbnail サムネイル画像の URL を返すかどうか
     * @returns キャプチャ画像の URL
     */
    static getCaptureImageURL(filename: string, thumbnail: boolean = false): string {
        const params = thumbnail ? '?thumbnail=true' : '';
        return `${Utils.api_base_url}/captures/${encodeURIComponent(filename)}${params}`;
    }

    /**
     * キャプチャ画像をサーバーの保存先フォルダから削除する
     * @param filename 削除するキャプチャ画像のファイル名
     * @returns 削除に成功した場合は true
     */
    static async deleteCapture(filename: string): Promise<boolean> {
        const response = await APIClient.delete(`/captures/${encodeURIComponent(filename)}`);
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'キャプチャの削除に失敗しました。');
            return false;
        }
        return true;
    }

    // ***** キャプチャフォルダ *****

    /**
     * ログインユーザーのキャプチャフォルダ一覧を取得する
     * @returns フォルダ一覧 (取得に失敗した場合・未ログインの場合は null)
     */
    static async fetchFolders(): Promise<ICaptureFolders | null> {
        const response = await APIClient.get<ICaptureFolders>('/captures/folders');
        if (response.type === 'error') {
            // 未ログイン (401) はフォルダ機能を使わないだけなので、エラーメッセージは出さない
            if (response.status !== 401) {
                APIClient.showGenericError(response, 'キャプチャフォルダ一覧の取得に失敗しました。');
            }
            return null;
        }
        return response.data;
    }

    /**
     * キャプチャフォルダを作成する
     * @param name フォルダ名
     * @returns 作成されたフォルダ (作成に失敗した場合は null)
     */
    static async createFolder(name: string): Promise<ICaptureFolder | null> {
        const response = await APIClient.post<ICaptureFolder>('/captures/folders', {name});
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'キャプチャフォルダの作成に失敗しました。');
            return null;
        }
        return response.data;
    }

    /**
     * キャプチャフォルダの名前・表示順序を更新する
     * @param folderId 更新するフォルダの ID
     * @param updates 更新する内容 (name / sort_order のいずれか、または両方)
     * @returns 更新後のフォルダ (更新に失敗した場合は null)
     */
    static async updateFolder(
        folderId: number,
        updates: {name?: string; sort_order?: number},
    ): Promise<ICaptureFolder | null> {
        const response = await APIClient.put<ICaptureFolder>(`/captures/folders/${folderId}`, updates);
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'キャプチャフォルダの更新に失敗しました。');
            return null;
        }
        return response.data;
    }

    /**
     * キャプチャフォルダを削除する
     * フォルダに登録されていたキャプチャの紐付けは消えるが、キャプチャ画像自体は削除されない。
     * @param folderId 削除するフォルダの ID
     * @returns 削除に成功した場合は true
     */
    static async deleteFolder(folderId: number): Promise<boolean> {
        const response = await APIClient.delete(`/captures/folders/${folderId}`);
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'キャプチャフォルダの削除に失敗しました。');
            return false;
        }
        return true;
    }

    /**
     * 指定されたフォルダに登録されているキャプチャ一覧を取得する
     * @param folderId フォルダ ID
     * @param order ソート順序 ('desc': 新しい順, 'asc': 古い順)
     * @param page ページ番号 (1始まり)
     * @returns キャプチャ一覧 (取得に失敗した場合は null)
     */
    static async fetchFolderCaptures(
        folderId: number,
        order: 'desc' | 'asc' = 'desc',
        page: number = 1,
    ): Promise<ICaptures | null> {
        const response = await APIClient.get<ICaptures>(`/captures/folders/${folderId}/captures`, {
            params: {order, page},
        });
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'フォルダ内のキャプチャ一覧の取得に失敗しました。');
            return null;
        }
        return response.data;
    }

    /**
     * 指定されたフォルダにキャプチャを一括追加する
     * 既に登録済みのキャプチャは無視される。
     * @param folderId フォルダ ID
     * @param filenames 追加するキャプチャ画像のファイル名リスト
     * @returns 追加に成功した場合は true
     */
    static async addCapturesToFolder(folderId: number, filenames: string[]): Promise<boolean> {
        const response = await APIClient.post(`/captures/folders/${folderId}/captures`, {filenames});
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'フォルダへのキャプチャの追加に失敗しました。');
            return false;
        }
        return true;
    }

    /**
     * 指定されたフォルダからキャプチャの登録を一括解除する
     * 紐付けを消すだけで、キャプチャ画像自体は削除されない。
     * @param folderId フォルダ ID
     * @param filenames 登録を解除するキャプチャ画像のファイル名リスト
     * @returns 解除に成功した場合は true
     */
    static async removeCapturesFromFolder(folderId: number, filenames: string[]): Promise<boolean> {
        const response = await APIClient.delete(`/captures/folders/${folderId}/captures`, {
            data: {filenames},
        });
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'フォルダからのキャプチャの削除に失敗しました。');
            return false;
        }
        return true;
    }
}

export default Captures;
