"""跨模块链路集成测试：覆盖教学诊改的核心业务数据流。"""
import pytest

from app.store import store
from app.services.observation import ObservationService
from app.services.feedback import FeedbackService
from app.services.improve_plan import ImprovePlanService
from app.services.improve_task import ImproveTaskService
from app.services.progress_log import ProgressLogService
from app.services.peer_review import PeerReviewService
from app.services.review_meeting import ReviewMeetingService
from app.services.semester_goal import SemesterGoalService
from app.services.lesson_prep import LessonPrepService
from app.services.exam_analysis import ExamAnalysisService
from app.services.quality_report import QualityReportService
from app.services.syllabus_rev import SyllabusRevService


def clear_all():
    """清理所有模块数据"""
    for name in store.module_names():
        store.rows(name).clear()


class TestObservationToFeedbackChain:
    """链路1: 观摩→反馈链 - 课堂观摩发现问题→创建教学反馈→生成改进方案"""

    def setup_method(self):
        clear_all()
        self.obs_svc = ObservationService()
        self.fb_svc = FeedbackService()
        self.plan_svc = ImprovePlanService()

    def test_observation_archived_then_feedback_signed_then_plan_approved(self):
        # Step 1: 创建并提交观摩记录
        obs, _ = self.obs_svc.create_entry({
            "教师姓名": "陈老师",
            "课程名称": "数据结构",
            "授课日期": "2025-10-20"
        })
        self.obs_svc.run_action(obs["id"], "提交记录")
        self.obs_svc.run_action(obs["id"], "归档记录")
        assert store.find("observation", obs["id"])["status"] == "已归档"

        # Step 2: 根据观摩创建反馈
        fb, _ = self.fb_svc.create_entry({
            "反馈对象": "陈老师",
            "反馈要点": "数据结构课堂互动不足",
            "改进建议": "增加算法示例互动环节",
            "反馈来源": f"observation:{obs['id']}"
        })
        self.fb_svc.run_action(fb["id"], "签收反馈")
        assert store.find("feedback", fb["id"])["status"] == "已签收"

        # Step 3: 根据已签收的反馈创建改进方案
        plan, _ = self.plan_svc.create_entry({
            "关联反馈": f"feedback:{fb['id']}",
            "改进目标": "提升数据结构教学互动性",
            "改进措施": "每周安排一次小组编程讨论"
        })
        self.plan_svc.run_action(plan["id"], "审核方案")
        assert store.find("improve_plan", plan["id"])["status"] == "审核通过"


class TestPlanToTaskChain:
    """链路2: 方案→任务链 - 改进方案通过审核→拆解为诊改任务→执行人员汇报进展"""

    def setup_method(self):
        clear_all()
        self.fb_svc = FeedbackService()
        self.plan_svc = ImprovePlanService()
        self.task_svc = ImproveTaskService()
        self.progress_svc = ProgressLogService()

    def test_plan_approved_then_task_created_then_progress_reported(self):
        # Step 1: 创建已签收的反馈和审核通过的方案
        fb, _ = self.fb_svc.create_entry({
            "反馈对象": "刘老师",
            "反馈要点": "学生编程作业正确率低",
            "改进建议": "增加课堂编程练习"
        })
        self.fb_svc.run_action(fb["id"], "签收反馈")

        plan, _ = self.plan_svc.create_entry({
            "关联反馈": f"feedback:{fb['id']}",
            "改进目标": "提升编程作业正确率至85%",
            "改进措施": "增加实践课时并设置编程考核"
        })
        self.plan_svc.run_action(plan["id"], "审核方案")

        # Step 2: 基于通过的方案创建诊改任务
        task, _ = self.task_svc.create_entry({
            "任务描述": "增加数据结构实践课时",
            "承接方案": f"plan:{plan['id']}",
            "执行人员": "赵老师"
        })
        self.task_svc.run_action(task["id"], "认领任务")
        assert store.find("improve_task", task["id"])["status"] == "执行中"

        # Step 3: 记录进展
        log, _ = self.progress_svc.create_entry({
            "关联方案": f"plan:{plan['id']}",
            "当前阶段": "第一阶段:增加实践课时",
            "完成情况": "已完成50%，学生反馈良好"
        })
        self.progress_svc.run_action(log["id"], "确认进展")
        assert store.find("progress_log", log["id"])["status"] == "已确认"


class TestPeerReviewToFeedbackChain:
    """链路3: 评议→反馈链 - 同行评议结果→汇总后触发教学反馈→关联改进目标"""

    def setup_method(self):
        clear_all()
        self.review_svc = PeerReviewService()
        self.fb_svc = FeedbackService()
        self.goal_svc = SemesterGoalService()

    def test_peer_review_triggers_feedback_when_improvement_needed(self):
        # Step 1: 创建同行评议，评议意见包含改进
        review, _ = self.review_svc.create_entry({
            "被评教师": "孙老师",
            "评议维度": "教学质量",
            "得分": "70",
            "评议意见": "教学方法需要改进，建议增加互动环节"
        })
        self.review_svc.run_action(review["id"], "汇总评议")

        # Step 2: 验证评议汇总后自动创建了反馈
        fb_rows = store.rows("feedback")
        auto_fb = [r for r in fb_rows if str(r.get("反馈来源", "")) == f"peer_review:{review['id']}"]
        assert len(auto_fb) >= 1, "评议汇总后应自动创建教学反馈"

        # Step 3: 签收反馈并创建关联学期目标
        fb = auto_fb[0]
        self.fb_svc.run_action(fb["id"], "签收反馈")
        assert store.find("feedback", fb["id"])["status"] == "已签收"


class TestReviewMeetingToTaskChain:
    """链路4: 会议→纪要链 - 复盘会议→参会教师签认→决议分发→关联到诊改任务"""

    def setup_method(self):
        clear_all()
        self.meeting_svc = ReviewMeetingService()

    def test_meeting_signed_and_distributed_with_resolution_creates_task(self):
        # Step 1: 创建复盘会议并签认
        meeting, _ = self.meeting_svc.create_entry({
            "会议主题": "期中教学效果复盘",
            "参会人员": "教研室主任、全体教师",
            "召开日期": "2025-11-01",
            "决议事项": "需要成立专项教学改进任务组，针对薄弱课程制定改进方案"
        })
        self.meeting_svc.run_action(meeting["id"], "签认纪要")
        assert store.find("review_meeting", meeting["id"])["status"] == "已签认"

        # Step 2: 分发会议并检查是否创建了诊改任务
        self.meeting_svc.run_action(meeting["id"], "分发给教师")

        # Step 3: 验证决议调"任务"关键词时自动创建了诊改任务
        task_rows = store.rows("improve_task")
        auto_task = [r for r in task_rows if str(r.get("任务描述", "")).find(f"meeting:{meeting['id']}") != -1]
        assert len(auto_task) >= 1, "会议决议含任务关键词时应自动创建诊改任务"


class TestExamAnalysisToImprovePlanChain:
    """链路5: 试卷→改进链 - 试卷分析发现薄弱点→触发改进方案"""

    def setup_method(self):
        clear_all()
        self.exam_svc = ExamAnalysisService()

    def test_high_difficulty_triggers_improve_plan(self):
        # Step 1: 创建难度系数较高的试卷分析
        analysis, _ = self.exam_svc.create_entry({
            "考试名称": "期末数据结构考试",
            "任课教师": "郑老师",
            "参考人数": "120",
            "难度系数": "0.72"
        })
        self.exam_svc.run_action(analysis["id"], "审核分析")

        # Step 2: 验证自动创建了改进方案
        plan_rows = store.rows("improve_plan")
        auto_plan = [r for r in plan_rows if str(r.get("关联反馈", "")).find(f"exam:{analysis['id']}") != -1]
        assert len(auto_plan) >= 1, "难度系数>0.5时应自动创建改进方案"


class TestQualityReportToReviewMeetingChain:
    """链路6: 简报→会议链 - 质量简报签收→问题突出时触发复盘会议"""

    def setup_method(self):
        clear_all()
        self.report_svc = QualityReportService()

    def test_serious_problem_triggers_review_meeting(self):
        # Step 1: 创建含严重问题的质量简报并签收
        report, _ = self.report_svc.create_entry({
            "覆盖学期": "2025-秋季",
            "教学质量概况": "整体良好",
            "突出问题": "2023级计算机专业多门课程及格率低于60%，触发教学预警"
        })
        self.report_svc.run_action(report["id"], "签收简报")

        # Step 2: 验证自动触发了复盘会议
        meeting_rows = store.rows("review_meeting")
        auto_meeting = [r for r in meeting_rows if str(r.get("决议事项", "")).find(f"quality_report:{report['id']}") != -1]
        assert len(auto_meeting) >= 1, "简报含严重/预警问题时应收触发复盘会议"


class TestLessonPrepToPeerReviewChain:
    """链路7: 备课→评议链 - 集体备课→参与教师签阅→可触发同行评议"""

    def setup_method(self):
        clear_all()
        self.prep_svc = LessonPrepService()

    def test_lesson_prep_with_improvement_review_triggers_peer_review(self):
        # Step 1: 创建备课记录，课后反思含改进关键词
        prep, _ = self.prep_svc.create_entry({
            "备课章节": "第5章 图结构",
            "主备教师": "杨老师",
            "参与教师": "李老师、王老师",
            "课后反思": "本次备课需要改进教学主线设计，建议进行同行评议"
        })
        self.prep_svc.run_action(prep["id"], "签阅记录")

        # Step 2: 验证自动创建了同行评议
        review_rows = store.rows("peer_review")
        auto_review = [r for r in review_rows if str(r.get("评议意见", "")).find(f"lesson_prep:{prep['id']}") != -1]
        assert len(auto_review) >= 1, "备课课后反思含改进/评议时应触发同行评议"


class TestSyllabusRevToLessonPrepChain:
    """链路8: 大纲→备课链 - 大纲修订通过→影响集体备课章节"""

    def setup_method(self):
        clear_all()
        self.syllabus_svc = SyllabusRevService()
        self.prep_svc = LessonPrepService()

    def test_syllabus_approved_updates_related_lesson_prep(self):
        # Step 1: 创建大纲修订
        syllabus, _ = self.syllabus_svc.create_entry({
            "课程名称": "数据结构",
            "修订章节": "第5章 图结构",
            "原内容": "图的定义和基本术语",
            "修订内容": "图的定义、存储结构和深度优先搜索"
        })
        self.syllabus_svc.run_action(syllabus["id"], "审批修订")

        # Step 2: 创建相关备课记录
        prep, _ = self.prep_svc.create_entry({
            "备课章节": "第5章 图结构 - 数据结构",
            "主备教师": "杨老师",
            "参与教师": "李老师",
        })

        # Step 3: 大纲修订通过后标记相关备课记录
        self.syllabus_svc._flag_related_lesson_prep("数据结构", "图结构", syllabus["id"])
        prep_row = store.find("lesson_prep", prep["id"])
        assert f"大纲修订{syllabus['id']}已通过" in prep_row.get("备注说明", "")


class TestCrossModuleHelpers:
    """跨模块辅助函数测试"""

    def test_require_entity_found(self):
        from app.services.cross_module import require_entity
        from app.services.feedback import FeedbackService
        store.rows("feedback").clear()
        fb_svc = FeedbackService()
        entry, _ = fb_svc.create_entry({
            "反馈对象": "测试",
            "反馈要点": "测试要点",
            "改进建议": "测试建议"
        })
        found = require_entity("feedback", entry["id"], "测试")
        assert found["id"] == entry["id"]

    def test_require_entity_not_found(self):
        from app.services.cross_module import require_entity
        with pytest.raises(ValueError, match="跨模块校验失败"):
            require_entity("feedback", 99999, "测试")

    def test_check_entity_status_valid(self):
        from app.services.cross_module import check_entity_status
        from app.services.feedback import FeedbackService
        store.rows("feedback").clear()
        fb_svc = FeedbackService()
        entry, _ = fb_svc.create_entry({
            "反馈对象": "测试",
            "反馈要点": "测试要点",
            "改进建议": "测试建议"
        })
        fb_svc.run_action(entry["id"], "签收反馈")
        found = check_entity_status("feedback", entry["id"], ["已签收", "已办结"], "测试")
        assert found["status"] == "已签收"

    def test_check_entity_status_invalid(self):
        from app.services.cross_module import check_entity_status
        from app.services.feedback import FeedbackService
        store.rows("feedback").clear()
        fb_svc = FeedbackService()
        entry, _ = fb_svc.create_entry({
            "反馈对象": "测试",
            "反馈要点": "测试要点",
            "改进建议": "测试建议"
        })
        with pytest.raises(ValueError, match="跨模块校验失败"):
            check_entity_status("feedback", entry["id"], ["已签收"], "测试")

    def test_semantic_chain_end_to_end(self):
        """全链路端到端测试：观摩→反馈→方案→任务→进展"""
        clear_all()
        obs_svc = ObservationService()
        fb_svc = FeedbackService()
        plan_svc = ImprovePlanService()
        task_svc = ImproveTaskService()
        progress_svc = ProgressLogService()

        # 观摩
        obs, _ = obs_svc.create_entry({
            "教师姓名": "全链路测试老师",
            "课程名称": "操作系统",
            "授课日期": "2025-12-01"
        })
        obs_svc.run_action(obs["id"], "提交记录")
        obs_svc.run_action(obs["id"], "归档记录")

        # 反馈
        fb, _ = fb_svc.create_entry({
            "反馈对象": "全链路测试老师",
            "反馈要点": "操作系统理论讲解欠缺",
            "改进建议": "增加实验课的案例演示",
            "反馈来源": f"observation:{obs['id']}"
        })
        fb_svc.run_action(fb["id"], "签收反馈")

        # 方案
        plan, _ = plan_svc.create_entry({
            "关联反馈": f"feedback:{fb['id']}",
            "改进目标": "提升操作系统教学质量",
            "改进措施": "增加实验课案例演示环节"
        })
        plan_svc.run_action(plan["id"], "审核方案")

        # 任务
        task, _ = task_svc.create_entry({
            "任务描述": "设计操作系统实验课案例",
            "承接方案": f"plan:{plan['id']}",
            "执行人员": "课程组组长"
        })
        task_svc.run_action(task["id"], "认领任务")

        # 进展
        log, _ = progress_svc.create_entry({
            "关联方案": f"plan:{plan['id']}",
            "当前阶段": "案例设计",
            "完成情况": "已完成3个实验案例的设计"
        })
        progress_svc.run_action(log["id"], "确认进展")

        # 验证全链路状态
        assert store.find("observation", obs["id"])["status"] == "已归档"
        assert store.find("feedback", fb["id"])["status"] == "已签收"
        assert store.find("improve_plan", plan["id"])["status"] == "审核通过"
        assert store.find("improve_task", task["id"])["status"] == "执行中"
        assert store.find("progress_log", log["id"])["status"] == "已确认"