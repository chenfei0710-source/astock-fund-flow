#!/bin/bash
# 一键部署到 GitHub Pages
REPO="chenfei0710/astock-fund-flow"

echo ""
echo "═══════════════════════════════════════════"
echo "  A股资金流向 - GitHub 一键部署"
echo "═══════════════════════════════════════════"
echo ""
echo "需要一个 GitHub Token（用于推送代码）"
echo "现在自动打开网页，请按以下步骤操作："
echo ""
echo "  1. 页面打开后，点 'Generate new token (classic)'"
echo "  2. Note 随便填（如：fund-flow）"
echo "  3. Expiration 选 'No expiration'"
echo "  4. 勾选 'repo'（第一个大复选框）"
echo "  5. 滚到最下面点 'Generate token'"
echo "  6. 复制那串字母数字"
echo ""
read -p "按回车键打开 GitHub Token 页面..."
open "https://github.com/settings/tokens/new?description=fund-flow&scopes=repo"
echo ""
read -s -p "请把 Token 粘贴到这里（输入时不显示，正常的）: " TOKEN
echo ""

if [ -z "$TOKEN" ]; then
  echo "❌ Token 不能为空"
  exit 1
fi

cd "$(dirname "$0")"

echo ""
echo "正在推送代码..."
git remote set-url origin "https://${TOKEN}@github.com/${REPO}.git"
git push -u origin main 2>&1

if [ $? -ne 0 ]; then
  echo "❌ 推送失败，请检查 Token 是否正确"
  exit 1
fi

echo ""
echo "正在开启 GitHub Pages..."
curl -s -X POST \
  -H "Authorization: token $TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/${REPO}/pages" \
  -d '{"source":{"branch":"main","path":"/"}}' > /dev/null

echo ""
echo "正在设置 Actions 自动触发权限..."
curl -s -X PUT \
  -H "Authorization: token $TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/${REPO}/actions/permissions/workflow" \
  -d '{"default_workflow_permissions":"write","can_approve_pull_request_reviews":true}' > /dev/null

# 清除 token（安全）
git remote set-url origin "https://github.com/${REPO}.git"

echo ""
echo "═══════════════════════════════════════════"
echo "  ✅ 部署完成！"
echo ""
echo "  网页地址（约1分钟后生效）："
echo "  https://chenfei0710.github.io/astock-fund-flow"
echo ""
echo "  每个交易日 15:35 自动更新数据"
echo "═══════════════════════════════════════════"
echo ""
