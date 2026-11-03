import unittest
from pathlib import Path


class MetadataStatConsistencyTest(unittest.TestCase):
    """録画情報のサイズ・更新時刻が、duration と同じ時点の値であることを検証する。

    FFprobe の解析中にもファイルの書き込みは進む。解析後に stat を取ると、
    duration は解析開始時点、サイズと更新時刻は解析終了時点の値になり、
    1 レコードの中で時点が食い違う。すると RecordedScanTask の
    「サイズも更新時刻も前回と同じならスキップ」が常に成立し、
    書き込み中の短い duration が再解析されずに残る。
    """

    def _source(self) -> str:
        """MetadataAnalyzer のソースを返す。

        Returns:
            str: ソースコード。
        """

        path = Path(__file__).resolve().parent.parent / 'app/metadata/MetadataAnalyzer.py'
        return path.read_text()

    def test_pre_stat_is_taken_before_ffprobe(self) -> None:
        """FFprobe の実行前に stat を控えている。"""

        source = self._source()
        pre_stat_at = source.find('pre_stat = self.recorded_file_path.stat()')
        ffprobe_at = source.find('result = self.__analyzeFFprobe()')

        self.assertGreater(pre_stat_at, 0, 'pre_stat の取得が見つかりません')
        self.assertGreater(ffprobe_at, 0, '__analyzeFFprobe() の呼び出しが見つかりません')
        self.assertLess(pre_stat_at, ffprobe_at, 'stat は FFprobe より前に取る必要があります')

    def test_recorded_video_uses_pre_stat(self) -> None:
        """RecordedVideo のサイズと更新時刻に解析前の値を使う。"""

        source = self._source()
        # RecordedVideo を組み立てる箇所で stat を取り直していない
        self.assertIn('stat_info = pre_stat', source)

        # 組み立て箇所より後で recorded_file_path.stat() を呼んでいない
        build_at = source.find('recorded_video = schemas.RecordedVideo(')
        self.assertGreater(build_at, 0)
        after_build = source[build_at:]
        self.assertNotIn(
            'stat_info = self.recorded_file_path.stat()',
            after_build,
            'RecordedVideo の組み立てで stat を取り直すと、duration と時点がずれます',
        )

    def test_mmt_analyzer_takes_stat_before_analysis(self) -> None:
        """MMT/TLV 経路でも、解析の前に stat を取っている。"""

        source = self._source()
        mmt_at = source.find('if MMTSInfoAnalyzer.probe(self.recorded_file_path) is True:')
        self.assertGreater(mmt_at, 0)
        block = source[mmt_at:mmt_at + 900]

        stat_at = block.find('stat_info = self.recorded_file_path.stat()')
        analyze_at = block.find('recorded_program = analyzer.analyze(')
        self.assertGreater(stat_at, 0)
        self.assertGreater(analyze_at, 0)
        self.assertLess(stat_at, analyze_at, 'MMT/TLV でも stat は解析より前に取る必要があります')
