"""测试各模块的业务约束：状态流转、幂等、冲突检测。"""
import pytest

from app.services.observation import ObservationService
from app.services.feedback import FeedbackService
from app.services.improve_plan import ImprovePlanService
from app.services.improve_task import ImproveTaskService
from app.services.progress_log import ProgressLogService
from app.services.peer_review import PeerReviewService
from app.services.review_meeting import ReviewMeetingService
from app.services.teach_record import TeachRecordService
from app.services.semester_goal import SemesterGoalService
from app.services.lesson_prep import LessonPrepService
from app.services.mentor_pair import MentorPairService
from app.services.exam_analysis import ExamAnalysisService
from app.services.quality_report import QualityReportService
from app.services.external_eval import ExternalEvalService
from app.services.class_schedule import ClassScheduleService
from app.services.resource_apply import ResourceApplyService
from app.services.teach_award import TeachAwardService
from app.services.textbook_select import TextbookSelectService
from app.services.course_group import CourseGroupService
from app.store import store


class TestObservationBusinessRules:
    """课堂观摩业务约束测试"""

    def setup_method(self):
        store.rows("observation").clear()
        self.svc = ObservationService()

    def test_archive_requires_submitted_status(self):
        entry, _ = self.svc.create_entry({"教师姓名": "李老师", "课程名称": "数学分析", "授课日期": "2025-09-10"})
        # 草稿状态不能直接归档
        result, msg = self.svc.run_action(entry["id"], "归档记录")
        assert result is None, "草稿状态不能直接归档"
        assert "先提交再归档" in msg

    def test_submit_then_archive_works(self):
        entry, _ = self.svc.create_entry({"教师姓名": "李老师", "课程名称": "数学分析", "授课日期": "2025-09-10"})
        result, _ = self.svc.run_action(entry["id"], "提交记录")
        assert result["status"] == "已提交"
        result2, _ = self.svc.run_action(entry["id"], "归档记录")
        assert result2["status"] == "已归档"

    def test_archived_cannot_return_to_draft(self):
        entry, _ = self.svc.create_entry({"教师姓名": "李老师", "课程名称": "数学分析", "授课日期": "2025-09-10"})
        self.svc.run_action(entry["id"], "提交记录")
        self.svc.run_action(entry["id"], "归档记录")
        result, msg = self.svc.run_action(entry["id"], "退回修改")
        assert result is None
        assert "不可退回修改" in msg


class TestFeedbackBusinessRules:
    """教学反馈业务约束测试"""

    def setup_method(self):
        store.rows("feedback").clear()
        self.svc = FeedbackService()

    def test_sign_feedback_is_idempotent(self):
        entry, _ = self.svc.create_entry({"反馈对象": "张老师", "反馈要点": "课堂互动不足", "改进建议": "增加提问环节"})
        result, _ = self.svc.run_action(entry["id"], "签收反馈")
        assert result["status"] == "已签收"
        # 重复签收应被拦截（幂等）
        result2, msg = self.svc.run_action(entry["id"], "签收反馈")
        assert result2 is None
        assert "无需重复签收" in msg

    def test_settled_feedback_cannot_be_signed(self):
        entry, _ = self.svc.create_entry({"反馈对象": "张老师", "反馈要点": "课堂互动不足", "改进建议": "增加提问环节"})
        self.svc.run_action(entry["id"], "签收反馈")
        self.svc.run_action(entry["id"], "确认办结")
        result, msg = self.svc.run_action(entry["id"], "签收反馈")
        assert result is None
        assert "已办结" in msg

    def test_cannot_settle_before_sign(self):
        entry, _ = self.svc.create_entry({"反馈对象": "张老师", "反馈要点": "课堂互动不足", "改进建议": "增加提问环节"})
        result, msg = self.svc.run_action(entry["id"], "确认办结")
        assert result is None
        assert "必须先签收" in msg

    def test_cannot_return_signed_feedback(self):
        entry, _ = self.svc.create_entry({"反馈对象": "张老师", "反馈要点": "课堂互动不足", "改进建议": "增加提问环节"})
        self.svc.run_action(entry["id"], "签收反馈")
        result, msg = self.svc.run_action(entry["id"], "退回重提")
        assert result is None
        assert "不可退回重提" in msg


class TestImprovePlanBusinessRules:
    """改进方案业务约束测试"""

    def setup_method(self):
        store.rows("improve_plan").clear()
        store.rows("feedback").clear()
        self.svc = ImprovePlanService()
        self.fb_svc = FeedbackService()

    def test_create_plan_with_approved_feedback(self):
        fb, _ = self.fb_svc.create_entry({"反馈对象": "王老师", "反馈要点": "教学方法单一", "改进建议": "引入互动式教学"})
        self.fb_svc.run_action(fb["id"], "签收反馈")
        # 使用 feedback:ID 格式引用
        plan, missing = self.svc.create_entry({
            "关联反馈": f"feedback:{fb['id']}",
            "改进目标": "提升教学互动性",
            "改进措施": "每月组织一次课堂互动观摩"
        })
        assert plan is not None
        assert missing == []

    def test_plan_cannot_be_approved_from_archived(self):
        plan, _ = self.svc.create_entry({
            "关联反馈": "反馈单#1",
            "改进目标": "提升教学互动性",
            "改进措施": "每月组织一次课堂互动观摩"
        })
        self.svc.run_action(plan["id"], "审核方案")
        # 审核通过后不能再审核
        result, msg = self.svc.run_action(plan["id"], "审核方案")
        assert result is None
        assert "不可审核" in msg


class TestSemesterGoalBusinessRules:
    """学期目标业务约束测试"""

    def setup_method(self):
        store.rows("semester_goal").clear()
        self.svc = SemesterGoalService()

    def test_no_duplicate_goals_for_same_teacher_semester(self):
        self.svc.create_entry({
            "目标描述": "提升教学评价满意度至90%",
            "量化指标": "满意度>=90%",
            "责任教师": "赵老师",
            "起始学期": "2025-秋季"
        })
        store.rows("semester_goal")[-1]["status"] = "已审定"
        with pytest.raises(ValueError, match="学期目标冲突"):
            self.svc.create_entry({
                "目标描述": "另一目标",
                "量化指标": "满意度>=95%",
                "责任教师": "赵老师",
                "起始学期": "2025-秋季"
            })

    def test_approve_checks_conflict(self):
        g1, _ = self.svc.create_entry({
            "目标描述": "提升教学评价满意度至90%",
            "量化指标": "满意度>=90%",
            "责任教师": "赵老师",
            "起始学期": "2025-秋季"
        })
        g2, _ = self.svc.create_entry({
            "目标描述": "第二目标",
            "量化指标": "满意度>=95%",
            "责任教师": "赵老师",
            "起始学期": "2025-秋季"
        })
        self.svc.run_action(g1["id"], "审定目标")
        result, msg = self.svc.run_action(g2["id"], "审定目标")
        assert result is None
        assert "冲突" in msg

    def test_abolish_requires_approved(self):
        g, _ = self.svc.create_entry({
            "目标描述": "提升教学评价满意度",
            "量化指标": "满意度>=90%",
            "责任教师": "赵老师",
        })
        result, msg = self.svc.run_action(g["id"], "废止目标")
        assert result is None
        assert "必须先审定" in msg


class TestMentorPairBusinessRules:
    """师徒结对业务约束测试"""

    def setup_method(self):
        store.rows("mentor_pair").clear()
        self.svc = MentorPairService()

    def test_mentor_cannot_be_in_multiple_active_pairs_same_period(self):
        self.svc.create_entry({
            "指导教师": "王老师",
            "青年教师": "小李",
            "结对目标": "提升教学能力",
            "起止日期": "2025-09至2026-01"
        })
        store.rows("mentor_pair")[-1]["status"] = "进行中"
        with pytest.raises(ValueError, match="结对冲突"):
            self.svc.create_entry({
                "指导教师": "王老师",
                "青年教师": "小张",
                "结对目标": "指导科研能力",
                "起止日期": "2025-09至2026-01"
            })

    def test_mentor_and_teacher_cannot_be_same(self):
        with pytest.raises(ValueError, match="不能是同一个人"):
            self.svc.create_entry({
                "指导教师": "王老师",
                "青年教师": "王老师",
                "结对目标": "自我提升"
            })


class TestClassScheduleBusinessRules:
    """排课编排业务约束测试"""

    def setup_method(self):
        store.rows("class_schedule").clear()
        self.svc = ClassScheduleService()

    def test_teacher_conflict_detection(self):
        self.svc.create_entry({
            "课程名称": "高等数学",
            "授课教师": "周老师",
            "上课时间": "周一1-2节"
        })
        store.rows("class_schedule")[-1]["status"] = "已确认"
        with pytest.raises(ValueError, match="排课冲突"):
            self.svc.create_entry({
                "课程名称": "线性代数",
                "授课教师": "周老师",
                "上课时间": "周一1-2节"
            })


class TestResourceApplyBusinessRules:
    """教学资源申请业务约束测试"""

    def setup_method(self):
        store.rows("resource_apply").clear()
        self.svc = ResourceApplyService()

    def test_resource_conflict_detection(self):
        self.svc.create_entry({
            "申请资源": "多媒体教室A",
            "用途说明": "上公开课",
            "使用时间": "2025-10-15上午"
        })
        store.rows("resource_apply")[-1]["status"] = "已批准"
        with pytest.raises(ValueError, match="资源冲突"):
            self.svc.create_entry({
                "申请资源": "多媒体教室A",
                "用途说明": "上公开课",
                "使用时间": "2025-10-15上午"
            })


class TestTextbookSelectBusinessRules:
    """教材选用业务约束测试"""

    def setup_method(self):
        store.rows("textbook_select").clear()
        self.svc = TextbookSelectService()

    def test_same_course_semester_cannot_have_duplicate(self):
        self.svc.create_entry({
            "教材名称": "高等数学第七版",
            "主编": "同济大学",
            "出版社": "高等教育出版社",
            "适用课程": "高等数学A",
            "选用学期": "2025-秋季"
        })
        store.rows("textbook_select")[-1]["status"] = "审核通过"
        with pytest.raises(ValueError, match="教材冲突"):
            self.svc.create_entry({
                "教材名称": "高等数学第八版",
                "主编": "同济大学",
                "出版社": "高等教育出版社",
                "适用课程": "高等数学A",
                "选用学期": "2025-秋季"
            })

    def test_order_requires_approved(self):
        entry, _ = self.svc.create_entry({
            "教材名称": "高等数学第七版",
            "主编": "同济大学",
            "出版社": "高等教育出版社",
        })
        result, msg = self.svc.run_action(entry["id"], "确认订购")
        assert result is None
        assert "先审核通过" in msg


class TestTeachAwardBusinessRules:
    """教学成果申报业务约束测试"""

    def setup_method(self):
        store.rows("teach_award").clear()
        self.svc = TeachAwardService()

    def test_submit_requires_approved(self):
        entry, _ = self.svc.create_entry({
            "成果名称": "智慧课堂研究",
            "完成团队": "教学改革组",
            "成果概要": "基于数据分析的教学方法改进",
        })
        result, msg = self.svc.run_action(entry["id"], "上报评审")
        assert result is None
        assert "先初审通过" in msg


class TestProgressLogBusinessRules:
    """进展记录业务约束测试"""

    def setup_method(self):
        store.rows("progress_log").clear()
        self.svc = ProgressLogService()

    def test_confirm_is_idempotent(self):
        entry, _ = self.svc.create_entry({
            "关联方案": "plan:1",
            "当前阶段": "第一阶段",
            "完成情况": "已完成80%"
        })
        result, _ = self.svc.run_action(entry["id"], "确认进展")
        assert result["status"] == "已确认"
        result2, msg = self.svc.run_action(entry["id"], "确认进展")
        assert result2 is None
        assert "无需重复确认" in msg

    def test_cannot_extend_confirmed_log(self):
        entry, _ = self.svc.create_entry({
            "关联方案": "plan:1",
            "当前阶段": "第一阶段",
            "完成情况": "已完成80%"
        })
        self.svc.run_action(entry["id"], "确认进展")
        result, msg = self.svc.run_action(entry["id"], "申请延期")
        assert result is None
        assert "不可再申请延期" in msg


class TestExternalEvalBusinessRules:
    """外部评估业务约束测试"""

    def setup_method(self):
        store.rows("external_eval").clear()
        self.svc = ExternalEvalService()

    def test_transfer_requires_received(self):
        entry, _ = self.svc.create_entry({
            "评估机构": "教育部评估中心",
            "评估指标": "教学质量综合评估",
            "评估结论": "良好"
        })
        result, msg = self.svc.run_action(entry["id"], "转办整改")
        assert result is None
        assert "先接收报告" in msg


class TestCrossModuleBusinessSnapshot:
    """跨模块业务快照测试"""

    def test_cross_module_snapshot_consistency(self):
        """测试跨模块数据快照的一致性"""
        from app.services.cross_module import module_snapshot
        snap = module_snapshot("feedback")
        assert "module" in snap
        assert "count" in snap
        assert "pending" in snap
        assert "abnormal" in snap