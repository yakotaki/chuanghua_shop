(function () {
  // Confirm delete in admin
  document.querySelectorAll('.js-confirm-delete').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      var ok = confirm('Confirm delete? / 确认删除？');
      if (!ok) e.preventDefault();
    });
  });
})();
