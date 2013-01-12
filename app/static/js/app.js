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

  $('.sortable').sortable().bind('sortupdate', function() {
    var ordering = {}
    
    $(this).find('> li[data-show-id]').each(function (index, element) {
      ordering[$(element).data('showId')] = index;
    });

    $.post('/ajax/showsorder', ordering);
  });

  $('#searchModal').on('show', function () {
    $('#search-results').html('<p class="lead">' + $('#search-results').data('placeholderText') + '</p>');
    $('#search-form input').val('');
    $('body').css('overflow', 'hidden');
  });

  $('#searchModal').on('shown', function () {
    $('#search-form input').focus();
  });

  $('#searchModal').on('hide', function () {
    $('body').css('overflow', 'auto');
  });

  $('#search-form').submit(function() {
    $('#search-results').html('<div class="progress progress-striped active"><div class="bar" style="width: 100%;"></div></div>');
    $('#search-results').load(SCRIPT_ROOT + '/ajax/search/' + encodeURIComponent($('#search-query').val()), function(response, textStatus, xhr) {
      if (xhr.status != 200) {
        $('#search-results').html('<p class="lead">' + $('#search-results').data('errorText') + '</p>');
      } else {
        $('#search-results a').click(function() {
          if ($(this).hasClass('disabled')) {
            return false;
          }

          $('#search-results a').addClass('disabled');
        });
      }
    });

    return false;
  });
}(window.jQuery);
