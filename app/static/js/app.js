!function ($) {
  "use strict";
  
  function setupButtons(context) {
    $('.btn[data-action="seen"]', context).click(function() {
      var button = $(this);

      if (button.hasClass('disabled')) {
        return;
      }

      var div = button.closest('div[data-show-id]');
      var showId = div.data('showId');
      var episodeId = button.data('episodeId');

      if (!showId || !episodeId) {
        throw new Error('No show and/or episode ID found');
      }

      button.find('> i').removeClass('icon-eye-open').addClass('icon-loader');
      button.addClass('disabled');

      $.getJSON(SCRIPT_ROOT + '/ajax/unseen/' + showId + '/' + episodeId, function(data, status, xhr) {
        if (xhr.status === 200) {
          div.html(data.unseen);
          setupButtons(div);
          $('table#upcoming').html(data.upcoming);
        }
      }).error(function () {
        button.find('> i').removeClass('icon-loader').addClass('icon-eye-open');
        button.removeClass('disabled');
      });
    });
  }

  setupButtons();
}(window.jQuery);
