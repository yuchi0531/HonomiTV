import Message from '@/message';
import APIClient from '@/services/APIClient';


/** Annict アカウントと個人用アクセストークンで連携するためのリクエストを表すインターフェイス */
export interface IAnnictAuthRequest {
    access_token: string;
}

/** Annict 作品と紐づいていないシリーズを表すインターフェイス */
export interface IAnnictUnlinkedSeries {
    id: number;
    title: string;
    annict_work_id: number | null;
    annict_work_name: string | null;
}

/** Annict の作品候補を表すインターフェイス */
export interface IAnnictWorkCandidate {
    id: number;
    title: string;
    title_kana: string | null;
    title_en: string | null;
    episodes_count: number | null;
}

class Annict {

    /**
     * Annict アカウントと個人用アクセストークンで連携する
     * @param auth_request Annict 個人用アクセストークン
     * @returns 連携に成功した場合は true、失敗した場合は false
     */
    static async loginAccount(auth_request: IAnnictAuthRequest): Promise<boolean> {

        // API リクエストを実行
        const response = await APIClient.post('/annict/auth', auth_request);

        // 無効な個人用アクセストークンは、再発行が必要なことを明示する
        if (response.type === 'error') {
            if (response.data.detail === 'Annict access token is invalid') {
                Message.error('Annict の個人用アクセストークンが無効です。');
                return false;
            }
            if (response.data.detail === 'Annict access token is empty') {
                Message.error('Annict の個人用アクセストークンを入力してください。');
                return false;
            }
            APIClient.showGenericError(response, 'Annict アカウントとの連携に失敗しました。');
            return false;
        }

        return true;
    }


    /**
     * 視聴記録の自動投稿のオン・オフを保存する
     * @param enabled 自動投稿する場合は true
     * @returns 保存に成功した場合は true、失敗した場合は false
     */
    static async updateAutoRecord(enabled: boolean): Promise<boolean> {

        // API リクエストを実行
        const response = await APIClient.put('/annict/auto-record', {enabled});

        // エラー処理
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'Annict の自動記録設定を更新できませんでした。');
            return false;
        }

        return true;
    }


    /**
     * 現在ログイン中のユーザーアカウントに紐づく Annict アカウントとの連携を解除する
     * @returns 連携解除に成功した場合は true、失敗した場合は false
     */
    static async logoutAccount(): Promise<boolean> {

        // API リクエストを実行
        const response = await APIClient.delete('/annict/logout');

        // エラー処理
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'Annict アカウントとの連携を解除できませんでした。');
            return false;
        }

        return true;
    }


    /**
     * Annict 作品と紐づいていないシリーズの一覧を取得する
     * @returns 未紐づけのシリーズ一覧 (取得できなかった場合は null)
     */
    static async fetchUnlinkedSeries(): Promise<IAnnictUnlinkedSeries[] | null> {

        // API リクエストを実行
        const response = await APIClient.get<{series_list: IAnnictUnlinkedSeries[]}>('/annict/unlinked-series');

        // エラー処理
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'Annict と未連携のシリーズを取得できませんでした。');
            return null;
        }

        return response.data.series_list;
    }


    /**
     * Annict に登録されている作品をタイトルで検索する
     * @param query 検索する作品タイトル
     * @returns 検索結果の作品一覧 (取得できなかった場合は null)
     */
    static async searchWorks(query: string): Promise<IAnnictWorkCandidate[] | null> {

        // API リクエストを実行
        const response = await APIClient.get<{works: IAnnictWorkCandidate[]}>('/annict/works/search', {params: {query}});

        // エラー処理
        if (response.type === 'error') {
            APIClient.showGenericError(response, 'Annict の作品を検索できませんでした。');
            return null;
        }

        return response.data.works;
    }


    /**
     * シリーズを Annict 作品へ手動で紐づける
     * @param series_id シリーズ番組の ID
     * @param annict_work_id 紐づける Annict 作品の ID
     * @returns 紐づけに成功した場合は true、失敗した場合は false
     */
    static async linkSeries(series_id: number, annict_work_id: number): Promise<boolean> {

        // API リクエストを実行
        const response = await APIClient.put(`/annict/series/${series_id}/link`, {annict_work_id});

        // エラー処理
        if (response.type === 'error') {
            if (response.data.detail === 'Specified Annict work is already linked to another series') {
                Message.error('この Annict 作品は既に別のシリーズに紐づいています。');
                return false;
            }
            APIClient.showGenericError(response, 'Annict 作品との紐づけに失敗しました。');
            return false;
        }

        return true;
    }
}

export default Annict;
